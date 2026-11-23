"""The multi-account coordinator is provided by DailyCheckin itself."""
import asyncio
import json
from types import SimpleNamespace

from daily_checkin.trae_accounts import TraeAccounts


def test_trae_account_settings_keep_legacy_location(tmp_path):
    async def run():
        coordinator = TraeAccounts(tmp_path)
        try:
            await coordinator.start()
            assert coordinator.snapshot() == {'accounts': [], 'auto_checkin_enabled': False}
            assert await coordinator.set_auto(True) == {'auto_checkin_enabled': True}
            assert json.loads((tmp_path / 'trae-cn' / 'settings.json').read_text(encoding='utf-8')) == {'auto_checkin_enabled': True}
        finally:
            await coordinator.close()
        reopened = TraeAccounts(tmp_path)
        try:
            assert reopened.snapshot()['auto_checkin_enabled'] is True
        finally:
            await reopened.close()
    asyncio.run(run())


def test_auto_service_init_failure_is_logged_without_credentials(tmp_path, monkeypatch):
    events = []
    account_id = 'a' * 32
    coordinator = TraeAccounts(tmp_path)
    coordinator.configure_logging(lambda event, **fields: events.append((event, fields)))
    monkeypatch.setattr(coordinator, '_records', lambda: [{'id': account_id, 'uid': 'private-user'}])
    monkeypatch.setattr(coordinator, '_settings', lambda: True)
    def fail(**kwargs):
        raise ValueError('secret-token in credential path')
    monkeypatch.setattr('daily_checkin.trae_scheduler.create_service', fail)
    async def run():
        try:
            await coordinator.start()
        finally:
            await coordinator.close()
    asyncio.run(run())
    event = next(fields for name, fields in events if name == 'trae_checkin_failure')
    assert event == {'brand': 'trae_cn', 'account_id': account_id, 'reason': 'startup',
                     'stage': 'service_init', 'error_type': 'value_error', 'failure_category': 'validation'}
    assert 'secret-token' not in repr(events)
    assert 'private-user' not in repr(events)


def test_host_logging_is_attached_before_automatic_service_start(tmp_path, monkeypatch):
    events = []
    account_id = 'b' * 32
    coordinator = TraeAccounts(tmp_path)
    coordinator.configure_logging(lambda event, **fields: events.append((event, fields)))
    monkeypatch.setattr(coordinator, '_records', lambda: [{'id': account_id, 'uid': 'private-user'}])
    monkeypatch.setattr(coordinator, '_settings', lambda: True)
    class Service:
        manager = SimpleNamespace(store=SimpleNamespace(account_id='private-user'))
        def set_diagnostic_account_id(self, value):
            self.account_id = value
        def configure_logging(self, callback):
            self.callback = callback
        async def start(self):
            self.callback('trae_test_started', account_id=self.account_id)
        async def close(self):
            pass
    monkeypatch.setattr('daily_checkin.trae_scheduler.create_service', lambda **kwargs: Service())
    async def run():
        try:
            await coordinator.start()
        finally:
            await coordinator.close()
    asyncio.run(run())
    assert ('trae_test_started', {'account_id': account_id}) in events
    assert any(name == 'trae_checkin_service_ready' and fields['reason'] == 'startup' for name, fields in events)
