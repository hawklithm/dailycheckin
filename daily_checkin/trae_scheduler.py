"""Trae CN daily activity scheduling using the shared check-in lifecycle."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import sqlite3
from typing import Callable

import httpx
from buddy_agent_auth.providers.trae.app_storage import root

from . import trae
from .trae_diagnostics import safe_error_fields
from .workbuddy import AccountCheckinService


class _Store:
    def __init__(self, account_id: str, directory: Path):
        self.account_id = account_id
        self.root = directory

    def list_accounts(self):
        return [{'id': self.account_id}]


class _Manager:
    def __init__(self, account_id: str, directory: Path):
        self.store = _Store(account_id, directory)
        self.enabled = True

    def has_account(self, account_id: str) -> bool:
        return self.store.account_id == account_id

    def get_settings(self):
        return {'auto_checkin_enabled': self.enabled}


class TraeCheckinService(AccountCheckinService):
    """Schedule a single configured Trae identity, reloading it for each operation.

    The expected user ID is pinned at construction. A native-client account
    switch or an updated credentials file is rejected until the service is
    deliberately restarted with the new identity.
    """

    def __init__(self, account_id: str, load_account: Callable[[], trae.Account],
                 directory: Path, *, client_factory=None, retry_delay=None, **kwargs):
        if not isinstance(account_id, str) or not account_id:
            raise ValueError('Trae account user ID is required for scheduling')
        kwargs.setdefault('random_delay', lambda: random.uniform(60.0, 600.0))
        super().__init__(_Manager(account_id, Path(directory)), **kwargs)
        self._retry_delay = retry_delay or (lambda: random.uniform(100.0, 200.0))
        self._last_midnight_date = None
        self._load_account = load_account
        self._client_factory = client_factory or (lambda: httpx.Client(timeout=30, trust_env=False))
        self._diagnostic_account_id = 'trae_' + hashlib.sha256(account_id.encode()).hexdigest()[:16]

    def set_diagnostic_account_id(self, account_id: str) -> None:
        # Host account IDs are opaque 32-character hex identifiers.
        if isinstance(account_id, str) and len(account_id) == 32 and all(c in '0123456789abcdef' for c in account_id):
            self._diagnostic_account_id = account_id

    def _log(self, event: str, **fields) -> None:
        fields['brand'] = 'trae_cn'
        if 'account_id' in fields:
            fields['account_id'] = self._diagnostic_account_id
        super()._log(event, **fields)

    def _operation(self, account_id: str, *, status_only: bool, before_claim=None, reason='manual'):
        try:
            account = self._load_account()
            if account.user_id != account_id:
                raise ValueError('Trae account changed; restart the scheduler')
        except Exception as exc:
            self._log('trae_checkin_failure', account_id=account_id, date=self._today(),
                      reason=reason, stage='load_account', **safe_error_fields(exc))
            raise
        with self._client_factory() as client:
            return trae.checkin(account, client, status_only=status_only, before_claim=before_claim,
                diagnostic=lambda **fields: self._log('trae_checkin_failure', account_id=account_id,
                    date=self._today(), reason=reason, **fields))

    @staticmethod
    def _bounded_delay(source, minimum, maximum):
        try:
            value = float(source())
        except (TypeError, ValueError, OverflowError):
            value = minimum
        return min(maximum, max(minimum, value)) if math.isfinite(value) else minimum

    async def _run_midnight(self, target_date):
        # The shared timer can wake just before midnight and invoke this twice.
        # One service owns one Trae account, so only schedule each date once.
        while self._now().date() < target_date and not self._stop_event.is_set():
            midnight = datetime.combine(target_date, datetime.min.time(), tzinfo=self._now().tzinfo)
            await self._sleep(max(0.01, (midnight - self._now()).total_seconds()))
        if self._stop_event.is_set() or self._today() != target_date.isoformat():
            return
        if self._last_midnight_date == target_date:
            return
        self._last_midnight_date = target_date
        await super()._run_midnight(target_date)

    async def _prepare_midnight(self, account_id: str, target_date: str, midnight: datetime):
        while self._before_post_allowed(account_id, target_date, True):
            result = await self.check_status(account_id, reason='midnight')
            status = result['status']
            if not self._before_post_allowed(account_id, target_date, True):
                break
            if status == 'unchecked':
                delay = self._bounded_delay(self._random_delay, 60.0, 600.0)
                # Delay is relative to the successful query, not midnight.
                due = self._now() + timedelta(seconds=delay)
                self._state(account_id)['next_checkin_at'] = due.timestamp()
                self._log('account_checkin_scheduled', account_id=account_id, date=target_date,
                          reason='midnight', status='unchecked', next_checkin_at=due.timestamp())
                key = (account_id, target_date)
                old = self._random_tasks.get(key)
                if old is not None and old is not asyncio.current_task() and not old.done():
                    old.cancel()
                self._random_tasks[key] = self._spawn(
                    self._random_followup(account_id, target_date, due), key=key)
                return
            if status not in {'error', 'unknown'}:
                self._log('account_checkin_midnight_skipped', account_id=account_id,
                          date=target_date, reason='midnight', status=status)
                return
            delay = self._bounded_delay(self._retry_delay, 100.0, 200.0)
            self._log('trae_checkin_retry_scheduled', account_id=account_id, date=target_date,
                      reason='midnight', status=status, next_checkin_at=self._epoch() + delay)
            await self._sleep(delay)
        self._log('account_checkin_midnight_skipped', account_id=account_id,
                  date=target_date, reason='midnight', status='disabled_or_expired')

    async def _check_status_locked(self, account_id: str, reason: str):
        state = self._state(account_id)
        state.update(status='checking', checked=None, error=None)
        try:
            async with self._semaphore:
                result = await asyncio.to_thread(self._operation, account_id, status_only=True, reason=reason)
            state['last_checked_at'] = self._epoch()
            if result['checked_in']:
                state.update(status='checked', checked=True, error=None, next_checkin_at=None)
            elif result.get('did_checked_in') is True:
                state.update(status='device_checked', checked=False, error=None, next_checkin_at=None)
            elif not result['enable']:
                self._set_error(state, '签到活动未开放')
                state['next_checkin_at'] = None
            else:
                state.update(status='unchecked', checked=False, error=None)
        except asyncio.CancelledError:
            state.update(status='unknown', checked=None, error=None, next_checkin_at=None)
            raise
        except Exception as exc:
            self._set_error(state, '签到状态查询失败')
            self._log('trae_checkin_failure', account_id=account_id, date=state['date'], reason=reason,
                      stage='status_operation', **safe_error_fields(exc))
        self._log('trae_checkin_status_checked', account_id=account_id, date=state['date'],
                  reason=reason, status=state['status'])
        return dict(state)

    async def _check_in_locked(self, account_id: str, reason: str, *, target_date: str,
                               require_enabled: bool):
        state = self._state(account_id)
        if self._today() != target_date:
            return dict(state)
        status = await self._check_status_locked(account_id, reason)
        state = self._state(account_id)
        if status['status'] != 'unchecked' or not self._before_post_allowed(account_id, target_date, require_enabled):
            self._log('trae_checkin_skipped', account_id=account_id, date=target_date, reason=reason,
                      stage='precheck', status=state['status'])
            return dict(state)
        marker = (account_id, target_date)
        with self._state_guard:
            if marker in self._post_started:
                self._set_error(state, '签到结果未确认')
                self._log('trae_checkin_skipped', account_id=account_id, date=target_date, reason=reason,
                          stage='attempt_ledger', outcome='already_attempted')
                return dict(state)
            self._post_started.add(marker)
        # Use a brand prefix even when host applications share an account store.
        ledger_id = 'trae-cn:' + account_id
        try:
            claimed = await asyncio.to_thread(self._attempt_ledger, ledger_id, target_date)
        except (OSError, sqlite3.Error) as exc:
            self._set_error(state, '签到结果未确认')
            self._log('trae_checkin_failure', account_id=account_id, date=target_date, reason=reason,
                      stage='attempt_ledger', **safe_error_fields(exc))
            return dict(state)
        if not claimed:
            self._set_error(state, '签到结果未确认')
            self._log('trae_checkin_skipped', account_id=account_id, date=target_date, reason=reason,
                      stage='attempt_ledger', outcome='already_attempted')
            return dict(state)
        state.update(status='signing', checked=False, error=None, next_checkin_at=None)
        try:
            async with self._semaphore:
                result = await asyncio.to_thread(
                    self._operation, account_id, status_only=False,
                    reason=reason,
                    before_claim=lambda: self._before_post_allowed(account_id, target_date, require_enabled))
        except asyncio.CancelledError:
            state.update(status='unknown', checked=None, error=None, next_checkin_at=None)
            raise
        except Exception as exc:
            self._set_error(state, '签到结果未确认')
            self._log('trae_checkin_failure', account_id=account_id, date=target_date, reason=reason,
                      stage='claim_operation', **safe_error_fields(exc))
            return dict(state)
        action = result.get('action')
        if action in {'cancelled', 'already_checked_in', 'device_already_checked_in', 'disabled'}:
            try:
                await asyncio.to_thread(self._attempt_ledger, ledger_id, target_date, clear=True)
            except (OSError, sqlite3.Error) as exc:
                self._set_error(state, '签到结果未确认')
                self._log('trae_checkin_failure', account_id=account_id, date=target_date, reason=reason,
                          stage='attempt_ledger_clear', **safe_error_fields(exc))
                return dict(state)
            with self._state_guard:
                self._post_started.discard(marker)
            if action == 'cancelled':
                state.update(status='unchecked', checked=False, error=None)
        if action in {'checked_in', 'already_checked_in'}:
            state.update(status='checked', checked=True, error=None, next_checkin_at=None,
                         last_checked_at=self._epoch())
            if action == 'checked_in':
                state['last_checkin_at'] = self._epoch()
        elif action == 'device_already_checked_in':
            state.update(status='device_checked', checked=False, error=None, next_checkin_at=None)
        elif action == 'disabled':
            self._set_error(state, '签到活动未开放')
        elif action != 'cancelled':
            self._set_error(state, '签到结果未确认')
        known = {'cancelled', 'checked_in', 'already_checked_in', 'device_already_checked_in', 'disabled', 'claim_accepted'}
        self._log('trae_checkin_finished', account_id=account_id, date=target_date,
                  reason=reason, status=state['status'], outcome=action if action in known else 'unknown')
        return dict(state)


def create_service(*, native: bool = False, creds: str | None = None,
                   device_id_source: str = 'get-device-id', base_url: str | None = None,
                   user_region: str | None = None) -> TraeCheckinService:
    """Create a pinned service for one native or independent Trae account."""
    if native == bool(creds):
        raise ValueError('choose exactly one Trae account source')
    if device_id_source not in {'existing', 'get-device-id'}:
        raise ValueError('invalid Trae device ID source')
    if not native and device_id_source != 'get-device-id':
        raise ValueError('device ID source applies only to native accounts')
    validated_url = trae.validate_base_url(base_url) if base_url else None
    def load_account():
        account = (trae.Account.from_native(device_id_source=device_id_source)
                   if native else trae.Account.from_file(creds))
        if validated_url:
            account = replace(account, base_url=validated_url)
        if user_region is not None:
            account = replace(account, user_region=user_region)
        return account
    account = load_account()
    return TraeCheckinService(account.user_id, load_account, root())


async def _run_scheduler(service: TraeCheckinService):
    try:
        await service.start()
        await asyncio.Event().wait()
    finally:
        await service.close()


def main(argv=None):
    parser = argparse.ArgumentParser(prog='daily-checkin trae schedule',
                                     description='Run Trae CN daily check-in until stopped')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--native', action='store_true', help='read the local Trae login')
    source.add_argument('--creds', help='independent Trae credentials file')
    parser.add_argument('--device-id-source', choices=['existing', 'get-device-id'])
    parser.add_argument('--base-url')
    parser.add_argument('--user-region')
    args = parser.parse_args(argv)
    if args.device_id_source and not args.native:
        parser.error('--device-id-source requires --native')
    try:
        service = create_service(native=args.native, creds=args.creds,
                                 device_id_source=args.device_id_source or 'get-device-id',
                                 base_url=args.base_url, user_region=args.user_region)
        service.configure_logging(lambda event, **fields: print(json.dumps(
            {'timestamp': datetime.now(timezone.utc).isoformat(), 'event': event, **fields},
            ensure_ascii=False), flush=True))
        try:
            asyncio.run(_run_scheduler(service))
        except KeyboardInterrupt:
            return 0
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({'timestamp': datetime.now(timezone.utc).isoformat(),
                          'event': 'trae_checkin_failure', 'brand': 'trae_cn',
                          'reason': 'startup', 'stage': 'service_init',
                          **safe_error_fields(exc)}, ensure_ascii=False))
        return 1
