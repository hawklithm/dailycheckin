"""Offline behavior of WorkBuddy CN cat travel and its duplicate guards."""
import asyncio
import multiprocessing
from pathlib import Path

import httpx
import pytest

from daily_checkin.workbuddy_travel import WorkBuddyTravelService, PREFIX


class Client:
    def ensure_authenticated(self, *, open_browser, allow_login):
        assert open_browser is False and allow_login is False
    def auth_headers(self):
        return {'Authorization': 'Bearer synthetic-token', 'X-User-Id': 'synthetic-user',
                'X-Refresh-Token': 'must-not-be-sent', 'X-Domain': 'example.test'}


class Store:
    def __init__(self, root, backend='domestic', endpoint='https://copilot.tencent.com'):
        self.root = Path(root)
        self.backend = backend
        self.endpoint = endpoint
    def list_accounts(self):
        return [{'id': 'account-1', 'backend': self.backend, 'endpoint': self.endpoint}]
    def get_client(self, account_id):
        assert account_id == 'account-1'
        return Client()


def _ledger_worker(root, ready, go, results):
    travel = WorkBuddyTravelService(Store(root))
    ready.put(True)
    go.wait(10)
    try:
        results.put(travel._ledger('account-1', 'depart', '2026-11-24'))
    except Exception as exc:
        results.put(type(exc).__name__)


def test_ledger_is_atomic_across_processes(tmp_path):
    ctx = multiprocessing.get_context('spawn')
    ready, results, go = ctx.Queue(), ctx.Queue(), ctx.Event()
    processes = [ctx.Process(target=_ledger_worker, args=(str(tmp_path), ready, go, results)) for _ in range(2)]
    for process in processes:
        process.start()
    try:
        assert ready.get(timeout=15) and ready.get(timeout=15)
        go.set()
        assert sorted([results.get(timeout=15), results.get(timeout=15)]) == [False, True]
    finally:
        for process in processes:
            process.join(5)
            if process.is_alive():
                process.terminate()
                process.join(5)


def service(root, handler, **kwargs):
    return WorkBuddyTravelService(Store(root),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kwargs)


def test_idle_dispatch_and_web_headers(tmp_path):
    requests = []
    async def handler(request):
        requests.append(request)
        assert request.url.host == 'www.codebuddy.cn'
        assert request.headers['origin'] == 'https://www.codebuddy.cn'
        assert request.headers['referer'].endswith('/profile/growth-center')
        assert request.headers['x-client-platform'] == 'web'
        assert request.headers['authorization'] == 'Bearer synthetic-token'
        assert 'x-refresh-token' not in request.headers
        if request.url.path.endswith('/status'):
            return httpx.Response(200, json={'code': 0, 'data': {'state': 'idle', 'daily_limit_reached': False}})
        if request.url.path.endswith('/config'):
            return httpx.Response(200, json={'code': 0, 'data': {'enabled': True, 'locations': [{'id': 42}]}})
        assert request.content == b'{"location_id":42}'
        return httpx.Response(200, json={'code': 0, 'data': {'state': 'traveling'}})
    async def run():
        s = service(tmp_path, handler)
        assert (await s.run_account('account-1'))['action'] == 'departed'
        assert (await s.run_account('account-1'))['error'] == 'outcome_unknown'
        await s.close()
    asyncio.run(run())
    assert [r.url.path for r in requests].count(PREFIX + '/depart') == 1


@pytest.mark.parametrize('state,limit,action', [('traveling', False, 'traveling'), ('idle', True, 'daily_limit')])
def test_traveling_or_daily_limit_skips_writes(tmp_path, state, limit, action):
    methods = []
    async def handler(request):
        methods.append(request.method)
        return httpx.Response(200, json={'code': 200, 'data': {'state': state, 'daily_limit_reached': limit}})
    async def run():
        s = service(tmp_path, handler)
        assert (await s.run_account('account-1'))['action'] == action
        await s.close()
    asyncio.run(run())
    assert methods == ['GET']


def test_arrived_claim_and_cross_restart_deduplication(tmp_path):
    calls = []
    async def handler(request):
        calls.append(request)
        if request.method == 'POST':
            assert request.content == b'{"record_id":123}'
            return httpx.Response(200, json={'code': 0, 'data': {'reward_credit': 10}})
        return httpx.Response(200, json={'code': 0, 'data': {'state': 'arrived', 'record_id': 123}})
    async def run():
        for n in range(2):
            s = service(tmp_path, handler)
            result = await s.run_account('account-1')
            assert result.get('action' if n == 0 else 'error') == ('claimed' if n == 0 else 'outcome_unknown')
            await s.close()
    asyncio.run(run())
    assert sum(r.method == 'POST' for r in calls) == 1


def test_timeout_does_not_repeat_depart_after_restart(tmp_path):
    calls = []
    async def handler(request):
        calls.append(request.method)
        if request.method == 'POST':
            raise httpx.ReadTimeout('sensitive-token')
        if request.url.path.endswith('/status'):
            return httpx.Response(200, json={'code': 0, 'data': {'state': 'idle'}})
        return httpx.Response(200, json={'code': 0, 'data': {'locations': [{'id': 1}]}})
    async def run():
        for _ in range(2):
            s = service(tmp_path, handler)
            assert (await s.run_account('account-1'))['error'] == 'outcome_unknown'
            await s.close()
    asyncio.run(run())
    assert calls.count('POST') == 1


def test_http_408_claim_outcome_is_not_retried(tmp_path):
    posts = []
    async def handler(request):
        if request.method == 'POST':
            posts.append(1)
            return httpx.Response(408, json={'message': 'timeout'})
        return httpx.Response(200, json={'code': 0, 'data': {'state': 'arrived', 'record_id': 2}})
    async def run():
        s = service(tmp_path, handler)
        assert (await s.run_account('account-1'))['error'] == 'outcome_unknown'
        assert (await s.run_account('account-1'))['error'] == 'outcome_unknown'
        await s.close()
    asyncio.run(run())
    assert posts == [1]


def test_explicit_location_rejection_tries_next_location(tmp_path):
    bodies = []
    async def handler(request):
        if request.url.path.endswith('/status'):
            return httpx.Response(200, json={'code': 0, 'data': {'state': 'idle'}})
        if request.url.path.endswith('/config'):
            return httpx.Response(200, json={'code': 0, 'data': {'locations': [{'id': 1}, {'id': 2}]}})
        bodies.append(request.content)
        if len(bodies) == 1:
            return httpx.Response(400, json={'code': 42, 'message': 'location not available'})
        return httpx.Response(200, json={'code': 0, 'data': {}})
    async def run():
        s = service(tmp_path, handler)
        assert (await s.run_account('account-1'))['action'] == 'departed'
        await s.close()
    asyncio.run(run())
    assert bodies == [b'{"location_id":1}', b'{"location_id":2}']


def test_unknown_state_and_unsupported_accounts_never_send_action(tmp_path):
    calls = []
    async def handler(request):
        calls.append(request.method)
        return httpx.Response(200, json={'code': 0, 'data': {'state': 'mystery'}})
    async def run():
        s = service(tmp_path, handler)
        assert (await s.run_account('account-1'))['error'] == 'invalid_state'
        await s.close()
        s = WorkBuddyTravelService(Store(tmp_path, backend='global'))
        assert (await s.run_account('account-1'))['error'] == 'unsupported_region'
        await s.close()
        s = WorkBuddyTravelService(Store(tmp_path, endpoint='https://custom.example'))
        assert (await s.run_account('account-1'))['error'] == 'unsupported_endpoint'
        await s.close()
    asyncio.run(run())
    assert calls == ['GET']


def test_cross_service_concurrent_attempts_only_send_once(tmp_path):
    posts = []
    async def handler(request):
        if request.url.path.endswith('/status'):
            return httpx.Response(200, json={'code': 0, 'data': {'state': 'idle'}})
        if request.url.path.endswith('/config'):
            return httpx.Response(200, json={'code': 0, 'data': {'locations': [{'id': 1}]}})
        posts.append(1)
        return httpx.Response(200, json={'code': 0, 'data': {}})
    async def run():
        first, second = service(tmp_path, handler), service(tmp_path, handler)
        results = await asyncio.gather(first.run_account('account-1'), second.run_account('account-1'))
        assert sum(r.get('action') == 'departed' for r in results) == 1
        await first.close(); await second.close()
    asyncio.run(run())
    assert len(posts) == 1


def test_auto_default_off_and_enable_persists(tmp_path):
    async def handler(request):
        raise AssertionError('should not make a request')
    async def run():
        s = service(tmp_path, handler, interval=3600)
        assert s.enabled() is False
        await s.start()
        await asyncio.sleep(0)
        assert s.set_enabled(True) == {'enabled': True}
        assert s.enabled() is True
        assert s.set_enabled(False) == {'enabled': False}
        await s.close()
        assert service(tmp_path, handler).enabled() is False
    asyncio.run(run())


def test_missing_record_id_remains_guarded_across_midnight(tmp_path):
    from datetime import datetime, timedelta
    from daily_checkin.workbuddy_travel import BEIJING
    now = [datetime(2026, 11, 24, 23, 59, tzinfo=BEIJING)]
    posts = []
    async def handler(request):
        if request.method == 'POST':
            posts.append(request.content)
            raise httpx.ReadTimeout('unknown outcome')
        return httpx.Response(200, json={'code': 0, 'data': {'state': 'arrived'}})
    async def run():
        first = service(tmp_path, handler, clock=lambda: now[0])
        assert (await first.run_account('account-1'))['error'] == 'outcome_unknown'
        await first.close()
        now[0] += timedelta(minutes=2)
        second = service(tmp_path, handler, clock=lambda: now[0])
        assert (await second.run_account('account-1'))['error'] == 'outcome_unknown'
        await second.close()
    asyncio.run(run())
    assert posts == [b'{}']


def test_enabling_auto_travel_runs_and_disable_prevents_more_requests(tmp_path):
    requests = []
    finished = asyncio.Event()
    async def handler(request):
        requests.append(request.url.path)
        if request.url.path.endswith('/status'):
            return httpx.Response(200, json={'code': 0, 'data': {'state': 'idle'}})
        if request.url.path.endswith('/config'):
            return httpx.Response(200, json={'code': 0, 'data': {'locations': [{'id': 1}]}})
        finished.set()
        return httpx.Response(200, json={'code': 0, 'data': {}})
    async def run():
        s = service(tmp_path, handler, interval=3600)
        await s.start()
        await asyncio.sleep(0)
        assert requests == []
        s.set_enabled(True)
        await asyncio.wait_for(finished.wait(), timeout=5)
        s.set_enabled(False)
        await s.close()
    asyncio.run(run())
    assert requests.count(PREFIX + '/depart') == 1


def test_success_without_data_is_accepted(tmp_path):
    async def handler(request):
        if request.url.path.endswith('/status'):
            return httpx.Response(200, json={'code': 0, 'data': {'state': 'arrived', 'record_id': 1}})
        return httpx.Response(200, json={'code': 0})
    async def run():
        s = service(tmp_path, handler)
        assert (await s.run_account('account-1'))['action'] == 'claimed'
        await s.close()
    asyncio.run(run())


def test_standalone_cli_uses_explicit_account_and_status_only(tmp_path, monkeypatch, capsys):
    from daily_checkin import workbuddy_cli
    import buddy_agent_auth
    calls = []
    async def handler(request):
        calls.append(request.method)
        return httpx.Response(200, json={'code': 0, 'data': {'state': 'traveling'}})
    monkeypatch.setattr(buddy_agent_auth, 'AccountStore', lambda path: Store(tmp_path))
    monkeypatch.setattr(workbuddy_cli, 'WorkBuddyTravelService',
                        lambda store: WorkBuddyTravelService(store,
                            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    assert workbuddy_cli.main(['--accounts-dir', str(tmp_path), 'travel', 'status', '--account', 'account-1']) == 0
    assert 'traveling' in capsys.readouterr().out
    assert calls == ['GET']
