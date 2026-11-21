"""Offline Trae scheduling, identity, and at-most-once activity checks."""
import asyncio
from datetime import datetime, timezone, timedelta

import httpx
import pytest

from daily_checkin.trae import Account, CLAIM_PATH, STATUS_PATH
from daily_checkin.trae_scheduler import TraeCheckinService


@pytest.fixture(autouse=True)
def pair(monkeypatch):
    monkeypatch.setattr('buddy_agent_auth.providers.trae.app_storage.resolve_pair',
                        lambda user_id, device_id, client, version: (device_id, None))


def make_service(root, handler, *, load=None, **kwargs):
    load = load or (lambda: Account('fake-token', 'device', user_id='user1'))
    return TraeCheckinService('user1', load, root,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


def test_startup_catchup_checks_and_claims_once(tmp_path):
    paths, checked = [], [False]
    def handler(request):
        paths.append(request.url.path)
        if request.url.path == CLAIM_PATH:
            checked[0] = True
            return httpx.Response(200, json={'code': 0})
        return httpx.Response(200, json={'enable': True, 'checked_in': checked[0]})
    async def scenario():
        service = make_service(tmp_path, handler)
        await service.start()
        await asyncio.gather(*list(service._tasks))
        assert service.snapshot('user1')['checked'] is True
        await service.close()
    asyncio.run(scenario())
    assert paths.count(CLAIM_PATH) == 1
    assert paths.count(STATUS_PATH) == 3


def test_unconfirmed_claim_not_repeated_after_restart(tmp_path):
    paths = []
    def handler(request):
        paths.append(request.url.path)
        if request.url.path == CLAIM_PATH:
            raise httpx.ReadTimeout('unknown outcome')
        return httpx.Response(200, json={'enable': True, 'checked_in': False})
    async def scenario():
        for _ in range(2):
            service = make_service(tmp_path, handler)
            assert (await service.check_in('user1'))['status'] == 'error'
            await service.close()
    asyncio.run(scenario())
    assert paths.count(CLAIM_PATH) == 1


def test_native_account_switch_fails_before_request(tmp_path):
    requests = []
    service = make_service(tmp_path, lambda request: requests.append(request),
                           load=lambda: Account('token', 'device', user_id='another-user'))
    async def scenario():
        assert (await service.check_in('user1'))['status'] == 'error'
        await service.close()
    asyncio.run(scenario())
    assert requests == []


def test_device_already_checked_never_claims(tmp_path):
    paths = []
    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={'enable': True, 'checked_in': False, 'did_checked_in': True})
    async def scenario():
        service = make_service(tmp_path, handler)
        result = await service.check_in('user1')
        assert result['status'] == 'device_checked'
        assert result['checked'] is False
        await service.close()
    asyncio.run(scenario())
    assert paths == [STATUS_PATH]


def test_midnight_schedules_delayed_followup(tmp_path):
    now = datetime(2026, 11, 22, tzinfo=timezone(timedelta(hours=8)))
    handler = lambda request: httpx.Response(200, json={'enable': True, 'checked_in': False})
    async def scenario():
        service = make_service(tmp_path, handler, clock=lambda: now, random_delay=lambda: 90)
        await service._prepare_midnight('user1', '2026-11-22', now)
        assert service.snapshot('user1')['next_checkin_at'] == now.timestamp() + 90
        assert ('user1', '2026-11-22') in service._random_tasks
        await service.close()
    asyncio.run(scenario())


def test_claim_gate_prevents_request(tmp_path, monkeypatch):
    paths = []
    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={'enable': True, 'checked_in': False})
    async def scenario():
        service = make_service(tmp_path, handler)
        original = service._before_post_allowed
        calls = []
        def gate(*args):
            calls.append(True)
            return original(*args) if len(calls) == 1 else False
        monkeypatch.setattr(service, '_before_post_allowed', gate)
        assert (await service.check_in('user1'))['status'] == 'unchecked'
        await service.close()
    asyncio.run(scenario())
    assert CLAIM_PATH not in paths
