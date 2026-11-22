"""Multi-account Trae check-in coordination for host applications."""
from __future__ import annotations
import asyncio
import json
from buddy_agent_auth.providers.codebuddy.login_jobs import AccountManagerError
from buddy_agent_auth.providers.trae.accounts import TraeAccountAuth
from buddy_agent_auth.providers.codebuddy.account_store import _atomic_json
from .workbuddy_api import safe_checkin

def _safe_trae_checkin(value):
    if value is None:
        return None
    device_checked = isinstance(value, dict) and value.get('status') == 'device_checked'
    if device_checked:
        value = {**value, 'status': 'unchecked'}
    result = safe_checkin(value)
    if device_checked:
        result['status'] = 'device_checked'
    return result


class TraeCheckinAccounts:
    def _init_trae_checkin(self):
        self.services = {}
        self.started = False
        self.loop = None
        self.async_lock = asyncio.Lock()

    def _settings(self):
        path = self.root / 'settings.json'
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or type(data.get('auto_checkin_enabled')) is not bool:
                raise ValueError()
            return data['auto_checkin_enabled']
        except (OSError, ValueError):
            raise AccountManagerError('Trae 签到设置损坏', status_code=503) from None

    def snapshot(self):
        with self.lock:
            records = self._records()
            enabled = self._settings()
        for item in records:
            service = self.services.get(item['id'])
            item['checkin'] = _safe_trae_checkin(service.snapshot(item['uid'])) if service else None
        return {'accounts': records, 'auto_checkin_enabled': enabled}

    async def start(self):
        async with self.async_lock:
            self.started = True
            self.loop = asyncio.get_running_loop()
            if self._settings():
                for record in self._records():
                    try:
                        await self._service(record)
                    except Exception:
                        pass

    async def _service(self, record):
        account_id = record['id']
        service = self.services.get(account_id)
        if service is None:
            from daily_checkin.trae_scheduler import create_service
            service = await asyncio.to_thread(create_service, creds=str(self._path(account_id) / 'credentials.json'))
            if service.manager.store.account_id != record['uid']:
                raise ValueError('account mismatch')
            try:
                if self.started and self._settings():
                    await service.start()
            except Exception:
                await service.close()
                raise
            self.services[account_id] = service
        return service

    async def ensure_scheduled(self, account_id):
        async with self.async_lock:
            if self.started and self._settings():
                record = next((r for r in self._records() if r['id'] == account_id), None)
                if record:
                    try:
                        await self._service(record)
                    except Exception:
                        pass

    async def checkin(self, account_id, claim=False):
        async with self.async_lock:
            record = next((r for r in self._records() if r['id'] == account_id), None)
            if not record:
                raise AccountManagerError('未找到该账号', status_code=404)
            try:
                service = await self._service(record)
                result = await (service.check_in(record['uid'], reason='manual') if claim else service.check_status(record['uid'], reason='manual'))
                return _safe_trae_checkin(result)
            except Exception:
                raise AccountManagerError('签到请求失败，请检查登录状态', status_code=502) from None

    async def set_auto(self, enabled):
        async with self.async_lock:
            _atomic_json(self.root / 'settings.json', {'auto_checkin_enabled': enabled})
            services, self.services = self.services, {}
            for service in services.values():
                await service.close()
            if enabled and self.started:
                for record in self._records():
                    try:
                        await self._service(record)
                    except Exception:
                        pass
            return {'auto_checkin_enabled': enabled}

    async def delete(self, account_id):
        async with self.async_lock:
            with self.lock:
                if not any(r['id'] == account_id for r in self._records()):
                    raise AccountManagerError('未找到该账号', status_code=404)
                if any(j['target'] == account_id and j['status'] == 'pending' for j in self.jobs.values()):
                    raise AccountManagerError('请先取消该账号的登录任务', status_code=409)
            service = self.services.pop(account_id, None)
            if service:
                await service.close()
            self._delete_record(account_id)

    async def _close_checkins(self):
        async with self.async_lock:
            for service in self.services.values():
                await service.close()
            self.services.clear()
            self.started = False


class TraeAccounts(TraeAccountAuth, TraeCheckinAccounts):
    """Coordinate account authentication with the Trae check-in lifecycle."""
    def __init__(self, root):
        self._init_trae_auth(root)
        self._init_trae_checkin()

    def _login_committed(self, account_id):
        if self.loop and not self.loop.is_closed():
            asyncio.run_coroutine_threadsafe(self.ensure_scheduled(account_id), self.loop)

    async def close(self):
        self._stop_logins()
        await self._close_checkins()
