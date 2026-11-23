"""Offline Trae scheduling, identity, and at-most-once activity checks."""
import asyncio
from datetime import datetime, timezone, timedelta

import httpx
import pytest

from daily_checkin.trae import Account, CLAIM_PATH, STATUS_PATH
from daily_checkin.trae_scheduler import TraeCheckinService
from daily_checkin.trae_diagnostics import safe_error_fields


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


@pytest.mark.parametrize('failure,expected', [
    (httpx.ReadTimeout('secret-token sensitive-url'), ('status_query', 'timeout', None)),
    (httpx.Response(503, text='secret-token'), ('status_query', 'http_status', 503)),
    (httpx.Response(200, json={'code': 987, 'message': 'secret-token'}), ('status_query', 'business_error', None)),
])
def test_status_failure_logs_stage_and_safe_fields(tmp_path, failure, expected):
    events = []
    def handler(request):
        if isinstance(failure, Exception):
            raise failure
        return failure
    async def scenario():
        service = make_service(tmp_path, handler,
            load=lambda: Account('secret-token', 'secret-device', user_id='private-user'))
        service.manager.store.account_id = 'private-user'
        service.configure_logging(lambda event, **fields: events.append((event, fields)))
        try:
            assert (await service.check_status('private-user', reason='midnight'))['status'] == 'error'
        finally:
            await service.close()
    asyncio.run(scenario())
    event = next(fields for name, fields in events if name == 'trae_checkin_failure' and fields['stage'] == expected[0])
    assert event['error_type'] == expected[1]
    assert event.get('http_status') == expected[2]
    assert event['reason'] == 'midnight'
    assert event['brand'] == 'trae_cn'
    assert event['account_id'].startswith('trae_')
    if expected[1] == 'business_error':
        assert event['business_code'] == 987
    serialized = repr(events)
    assert all(secret not in serialized for secret in ('secret-token', 'secret-device', 'private-user', 'sensitive-url'))


def test_device_failure_identifies_stage_without_exception_message(tmp_path, monkeypatch):
    def fail(*args):
        raise ValueError('private device secret')
    monkeypatch.setattr('buddy_agent_auth.providers.trae.app_storage.resolve_pair', fail)
    events = []
    async def scenario():
        service = make_service(tmp_path, lambda request: pytest.fail('unexpected request'))
        service.configure_logging(lambda event, **fields: events.append((event, fields)))
        try:
            assert (await service.check_status('user1'))['status'] == 'error'
        finally:
            await service.close()
    asyncio.run(scenario())
    assert any(data.get('stage') == 'device_resolution' and data.get('error_type') == 'value_error'
               for _, data in events)
    assert 'private device secret' not in repr(events)


def test_duplicate_attempt_records_safe_skip_reason(tmp_path):
    events = []
    def handler(request):
        if request.url.path == CLAIM_PATH:
            raise httpx.ReadTimeout('private message')
        return httpx.Response(200, json={'enable': True, 'checked_in': False})
    async def scenario():
        for _ in range(2):
            service = make_service(tmp_path, handler)
            service.configure_logging(lambda event, **fields: events.append((event, fields)))
            assert (await service.check_in('user1'))['status'] == 'error'
            await service.close()
    asyncio.run(scenario())
    assert any(name == 'trae_checkin_skipped' and fields.get('outcome') == 'already_attempted'
               for name, fields in events)
    assert 'private message' not in repr(events)


@pytest.mark.parametrize('message,category,error_type,status', [
    ('login token expired; sign in to Trae again', 'authentication', 'token_expired', None),
    ('Trae account changed; restart the scheduler', 'authentication', 'account_mismatch', None),
    ('device activation was not confirmed', 'device', 'device_activation_unconfirmed', None),
    ('invalid device_pair.json; refusing to overwrite it', 'storage', 'device_pair_invalid', None),
    ('device registration failed: HTTP 503', 'upstream', 'device_registration_http_error', 503),
    ('device activation network error (ReadTimeout); not retried', 'network', 'timeout', None),
])
def test_known_local_errors_have_safe_categories(message, category, error_type, status):
    fields = safe_error_fields(ValueError(message))
    assert fields['failure_category'] == category
    assert fields['error_type'] == error_type
    assert fields.get('http_status') == status
    assert message not in repr(fields)


def test_cli_startup_failure_does_not_print_private_exception(monkeypatch, capsys):
    from daily_checkin import trae_scheduler
    def fail(**kwargs):
        raise ValueError('private-credential-path secret-token')
    monkeypatch.setattr(trae_scheduler, 'create_service', fail)
    assert trae_scheduler.main(['--creds', 'dummy.json']) == 1
    output = capsys.readouterr().out
    assert 'service_init' in output and 'value_error' in output
    assert 'private-credential-path' not in output and 'secret-token' not in output
