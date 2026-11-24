"""WorkBuddy CN cat travel: status, departure, reward claim and scheduling.

This module owns activity behavior only. Authentication stays in
buddy-agent-auth and the host supplies the account store.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

ORIGIN = 'https://www.codebuddy.cn'
PREFIX = '/activity/growth/buddy/travel'
BEIJING = timezone(timedelta(hours=8))
_ALLOWED_DOMESTIC_HOSTS = frozenset({'copilot.tencent.com', 'www.codebuddy.cn'})


def _business_error(message):
    text = message.lower() if isinstance(message, str) else ''
    if 'already traveling' in text:
        return 'already_traveling'
    if 'daily limit' in text or 'daily_limit' in text:
        return 'daily_limit'
    if 'no active buddy' in text:
        return 'no_buddy'
    if 'location not available' in text:
        return 'location_unavailable'
    if 'no unclaimed travel' in text:
        return 'already_claimed'
    if 'not arrived yet' in text:
        return 'not_arrived'
    return 'business_rejected'


class TravelError(Exception):
    def __init__(self, category: str, *, uncertain: bool = False):
        super().__init__(category)
        self.category = category
        self.uncertain = uncertain


class WorkBuddyTravelService:
    """Operate on saved CN accounts without switching the active account.

    Automatic mode is opt-in. A durable action ledger coordinates hosts sharing
    the account directory; uncertain POST outcomes remain blocked until the
    upstream status shows the action occurred or the user resolves the issue.
    """
    def __init__(self, store: Any, *, client_factory: Callable | None = None,
                 clock: Callable | None = None, interval: float = 900):
        self.store = store
        self.root = Path(store.root)
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=10.0, trust_env=False))
        self._clock = clock or (lambda: datetime.now(BEIJING))
        self._interval = interval
        self._locks: dict[str, asyncio.Lock] = {}
        self._task = None
        self._wake = None
        self._loop_ref = None
        self._started = False
        self._closed = False
        self._callback = None
        self._results: dict[str, dict] = {}

    def configure_logging(self, callback):
        self._callback = callback

    def _log(self, event, account_id, **fields):
        # Never emit upstream messages, payloads, tokens or account identifiers
        # other than the opaque local account ID.
        if self._callback:
            try:
                self._callback(event, account_id=account_id, brand='workbuddy', **fields)
            except Exception:
                pass

    @property
    def _settings_file(self):
        return self.root / 'workbuddy-travel-settings.json'

    def enabled(self):
        try:
            obj = json.loads(self._settings_file.read_text(encoding='utf-8'))
            return isinstance(obj, dict) and obj.get('enabled') is True
        except (OSError, ValueError):
            return False

    def set_enabled(self, enabled: bool):
        if type(enabled) is not bool:
            raise ValueError('enabled must be a boolean')
        self.root.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.travel-settings-', dir=self.root)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump({'enabled': enabled}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, self._settings_file)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        if self._wake:
            self._wake.set()
        return {'enabled': enabled}

    def _record(self, account_id):
        for record in self.store.list_accounts():
            if record.get('id') == account_id:
                return record
        raise TravelError('account_missing')

    def _client(self, account_id):
        record = self._record(account_id)
        if record.get('backend') != 'domestic':
            raise TravelError('unsupported_region')
        parts = urlsplit(str(record.get('endpoint') or ''))
        if parts.scheme != 'https' or parts.hostname not in _ALLOWED_DOMESTIC_HOSTS or parts.port not in (None, 443) or parts.username or parts.password or parts.path not in ('', '/') or parts.query or parts.fragment:
            raise TravelError('unsupported_endpoint')
        return self.store.get_client(account_id)

    async def _request(self, client, method, path, body=None, before_request=None):
        # Refresh only before a request; never automatically repeat an uncertain POST.
        try:
            await asyncio.to_thread(client.ensure_authenticated, open_browser=False, allow_login=False)
            auth = await asyncio.to_thread(client.auth_headers)
        except Exception:
            raise TravelError('authentication') from None
        names = {'authorization': 'Authorization', 'x-user-id': 'X-User-Id',
                 'x-enterprise-id': 'X-Enterprise-Id', 'x-tenant-id': 'X-Tenant-Id',
                 'x-domain': 'X-Domain'}
        headers = {names[k.lower()]: v for k, v in auth.items()
                   if isinstance(k, str) and k.lower() in names}
        if not headers.get('Authorization'):
            raise TravelError('authentication')
        headers.update({'Accept': 'application/json', 'Content-Type': 'application/json',
                        'x-client-platform': 'web', 'Origin': ORIGIN,
                        'Referer': ORIGIN + '/profile/growth-center'})
        if before_request is not None and not before_request():
            raise TravelError('disabled')
        try:
            async with self._client_factory() as http:
                response = await http.request(method, ORIGIN + PREFIX + path, headers=headers,
                                              **({'json': body} if method == 'POST' else {}))
        except httpx.HTTPError:
            raise TravelError('network', uncertain=method == 'POST') from None
        if not 200 <= response.status_code < 300:
            if method == 'POST' and 400 <= response.status_code < 500:
                try:
                    error = response.json()
                    if isinstance(error, dict) and type(error.get('code')) is int and error['code'] not in (0, 200):
                        category = _business_error(error.get('message') or error.get('msg'))
                        if category != 'business_rejected':
                            raise TravelError(category)
                except ValueError:
                    pass
            # A request timeout or server error may occur after the action.
            raise TravelError('http_' + str(response.status_code),
                              uncertain=method == 'POST' and
                              (response.status_code == 408 or not 400 <= response.status_code < 500))
        try:
            result = response.json()
        except ValueError:
            raise TravelError('invalid_response', uncertain=method == 'POST') from None
        if not isinstance(result, dict) or type(result.get('code')) is not int:
            raise TravelError('invalid_response', uncertain=method == 'POST')
        if result['code'] not in (0, 200):
            # The upstream message is inspected in memory only, never surfaced.
            message = result.get('message') or result.get('msg')
            raise TravelError(_business_error(message) if method == 'POST' else 'business_rejected')
        if method == 'POST' and result.get('data') is None:
            return {}
        if not isinstance(result.get('data'), dict):
            raise TravelError('invalid_response', uncertain=method == 'POST')
        return result['data']

    async def _status(self, client):
        data = await self._request(client, 'GET', '/status')
        state = data.get('state')
        if not isinstance(state, str) or state.strip().lower() not in {'idle', 'traveling', 'arrived'}:
            raise TravelError('invalid_state')
        daily_limit = data.get('daily_limit_reached', False)
        if type(daily_limit) is not bool:
            raise TravelError('invalid_state')
        record = data.get('record_id')
        return {'state': state.strip().lower(), 'daily_limit_reached': daily_limit,
                'record_id': record if type(record) is int and record > 0 else 0,
                'arrive_at': data.get('arrive_at') if type(data.get('arrive_at')) is int else None,
                'location_name': str((data.get('location') or {}).get('name') or '')[:100] if isinstance(data.get('location'), dict) else ''}

    def _ledger(self, account_id, action, key, *, clear=False):
        self.root.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.root / 'workbuddy-travel-attempts.sqlite3', timeout=5) as db:
            db.execute('CREATE TABLE IF NOT EXISTS attempts (account_id TEXT NOT NULL, action TEXT NOT NULL, '
                       'action_key TEXT NOT NULL, PRIMARY KEY(account_id, action, action_key))')
            if clear:
                db.execute('DELETE FROM attempts WHERE account_id=? AND action=? AND action_key=?', (account_id, action, key))
                return True
            return db.execute('INSERT OR IGNORE INTO attempts VALUES (?, ?, ?)', (account_id, action, key)).rowcount == 1

    def _today(self):
        now = self._clock()
        return now.astimezone(BEIJING).date().isoformat() if now.tzinfo else now.date().isoformat()

    async def status(self, account_id):
        try:
            client = self._client(account_id)
            result = {'ok': True, **(await self._status(client))}
        except TravelError as exc:
            result = {'ok': False, 'error': exc.category}
        except Exception:
            result = {'ok': False, 'error': 'unexpected'}
        self._results[account_id] = result
        return dict(result)

    def snapshot(self, account_id):
        return dict(self._results.get(account_id, {'ok': None, 'state': 'unknown'}))

    async def run_account(self, account_id, *, allow_depart=True, automatic=False):
        lock = self._locks.setdefault(account_id, asyncio.Lock())
        async with lock:
            try:
                client = self._client(account_id)
                status = await self._status(client)
                state = status['state']
                if state == 'traveling':
                    result = {'ok': True, 'action': 'traveling', **status}
                elif state == 'idle' and status['daily_limit_reached']:
                    result = {'ok': True, 'action': 'daily_limit', **status}
                elif state == 'idle' and not allow_depart:
                    result = {'ok': True, 'action': 'idle', **status}
                elif state == 'arrived':
                    # Without a record ID, crossing midnight cannot prove that
                    # this is a different trip; retain the same guard key.
                    key = str(status['record_id']) if status['record_id'] else 'unknown'
                    result = await self._perform(client, account_id, 'claim', key,
                        '/claim', {'record_id': status['record_id']} if status['record_id'] else {}, automatic)
                else:
                    config = await self._request(client, 'GET', '/config')
                    locations = config.get('locations')
                    if config.get('enabled', True) is not True or not isinstance(locations, list):
                        raise TravelError('no_location')
                    ids = [loc.get('id') for loc in locations if isinstance(loc, dict)
                           and type(loc.get('id')) in (str, int) and str(loc.get('id')).strip()]
                    if not ids:
                        raise TravelError('no_location')
                    result = None
                    for location_id in ids:
                        result = await self._perform(client, account_id, 'depart', self._today(), '/depart',
                                                     {'location_id': location_id}, automatic)
                        if result.get('error') != 'location_unavailable':
                            break
                self._results[account_id] = result
                self._log('workbuddy_travel_result', account_id, status=result.get('action', 'error'),
                          reason='automatic' if automatic else 'manual',
                          outcome=result.get('error') or result.get('action', 'unknown'))
                return dict(result)
            except TravelError as exc:
                result = {'ok': False, 'error': exc.category}
            except (OSError, sqlite3.Error):
                result = {'ok': False, 'error': 'storage'}
            except Exception:
                result = {'ok': False, 'error': 'unexpected'}
            self._results[account_id] = result
            self._log('workbuddy_travel_result', account_id, status='error',
                      reason='automatic' if automatic else 'manual', outcome=result['error'])
            return dict(result)

    async def _perform(self, client, account_id, action, key, path, body, automatic):
        if self._closed or (automatic and not self.enabled()):
            return {'ok': False, 'error': 'disabled'}
        claimed = await asyncio.to_thread(self._ledger, account_id, action, key)
        if not claimed:
            return {'ok': False, 'error': 'outcome_unknown'}
        # Recheck after the ledger wait and before any request is sent.
        if self._closed or (automatic and not self.enabled()):
            await asyncio.to_thread(self._ledger, account_id, action, key, clear=True)
            return {'ok': False, 'error': 'disabled'}
        try:
            data = await self._request(client, 'POST', path, body,
                before_request=lambda: not self._closed and (not automatic or self.enabled()))
        except TravelError as exc:
            if not exc.uncertain:
                await asyncio.to_thread(self._ledger, account_id, action, key, clear=True)
            if exc.category == 'already_traveling':
                return {'ok': True, 'action': 'traveling'}
            if exc.category == 'daily_limit':
                return {'ok': True, 'action': 'daily_limit'}
            if exc.category == 'already_claimed':
                return {'ok': True, 'action': 'already_claimed'}
            return {'ok': False, 'error': exc.category if not exc.uncertain else 'outcome_unknown'}
        return {'ok': True, 'action': 'departed' if action == 'depart' else 'claimed',
                **({'reward_credit': data.get('reward_credit')} if action == 'claim' and type(data.get('reward_credit')) in (int, float) else {})}

    async def _cycle(self, *, allow_depart):
        try:
            accounts = self.store.list_accounts()
        except Exception:
            return
        for record in accounts:
            if not self.enabled() or self._closed:
                return
            account_id = record.get('id') if isinstance(record, dict) else None
            if isinstance(account_id, str) and record.get('backend') == 'domestic':
                await self.run_account(account_id, allow_depart=allow_depart, automatic=True)

    async def _loop(self):
        tick = 0
        while not self._closed:
            if self.enabled():
                await self._cycle(allow_depart=(tick % 2 == 0))
                tick += 1
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval)
                self._wake.clear()
                tick = 0
            except asyncio.TimeoutError:
                pass

    async def start(self):
        if self._started or self._closed:
            return
        self._started = True
        self._loop_ref = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._task = asyncio.create_task(self._loop())

    def stop(self):
        self._closed = True
        if self._loop_ref and not self._loop_ref.is_closed() and self._task:
            self._loop_ref.call_soon_threadsafe(self._task.cancel)

    async def close(self):
        self.stop()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)
