"""Cross-process coordination for WorkBuddy daily activity attempts."""
import asyncio
import multiprocessing
from pathlib import Path

from fastapi.responses import Response
from daily_checkin.workbuddy import AccountCheckinService


class _Store:
    def __init__(self, root):
        self.root = Path(root)
    def list_accounts(self):
        return [{'id': 'account'}]
    def get_client(self, account_id):
        return object()


class _Manager:
    def __init__(self, root):
        self.store = _Store(root)
    def has_account(self, account_id):
        return account_id == 'account'
    def get_settings(self):
        return {'auto_checkin_enabled': False}


def _worker(root, ready, go, result):
    service = AccountCheckinService(_Manager(root))
    ready.put('ready')
    go.wait(10)
    try:
        result.put(service._attempt_ledger('account', '2026-11-21'))
    except Exception as exc:
        result.put(type(exc).__name__)


def test_attempt_claim_is_atomic_across_processes(tmp_path):
    ctx = multiprocessing.get_context('spawn')
    ready, results, go = ctx.Queue(), ctx.Queue(), ctx.Event()
    processes = [ctx.Process(target=_worker, args=(str(tmp_path), ready, go, results)) for _ in range(2)]
    for process in processes:
        process.start()
    try:
        assert ready.get(timeout=15) == ready.get(timeout=15) == 'ready'
        go.set()
        outcomes = [results.get(timeout=15), results.get(timeout=15)]
        assert sorted(outcomes) == [False, True], outcomes
        assert not AccountCheckinService(_Manager(tmp_path))._attempt_ledger('account', '2026-11-21')
        assert AccountCheckinService(_Manager(tmp_path))._attempt_ledger('account', '2026-11-22')
    finally:
        for process in processes:
            process.join(5)
            if process.is_alive():
                process.terminate()
                process.join(5)


def test_unknown_outcome_blocks_retry_after_service_restart(tmp_path):
    calls = []
    async def requester(client, method, path):
        calls.append(path)
        if path.endswith('checkin-activity-status'):
            return Response(content=b'{"code":0,"data":{"active":true,"today_checked_in":false}}', status_code=200)
        raise TimeoutError('unknown outcome')
    async def scenario():
        for _ in range(2):
            service = AccountCheckinService(_Manager(tmp_path), requester=requester)
            result = await service.check_in('account')
            assert result['status'] == 'error'
            await service.close()
    asyncio.run(scenario())
    assert sum(path.endswith('/daily-checkin') for path in calls) == 1
