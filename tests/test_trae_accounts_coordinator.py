"""The multi-account coordinator is provided by DailyCheckin itself."""
import asyncio
import json

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
