"""Trae CN daily activity scheduling using the shared check-in lifecycle."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from typing import Callable

import httpx
from buddy_agent_auth.providers.trae.app_storage import root

from . import trae
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
                 directory: Path, *, client_factory=None, **kwargs):
        if not isinstance(account_id, str) or not account_id:
            raise ValueError('Trae account user ID is required for scheduling')
        super().__init__(_Manager(account_id, Path(directory)), **kwargs)
        self._load_account = load_account
        self._client_factory = client_factory or (lambda: httpx.Client(timeout=30, trust_env=False))

    def _operation(self, account_id: str, *, status_only: bool, before_claim=None):
        account = self._load_account()
        if account.user_id != account_id:
            raise ValueError('Trae account changed; restart the scheduler')
        with self._client_factory() as client:
            return trae.checkin(account, client, status_only=status_only, before_claim=before_claim)

    async def _check_status_locked(self, account_id: str, reason: str):
        state = self._state(account_id)
        state.update(status='checking', checked=None, error=None)
        try:
            async with self._semaphore:
                result = await asyncio.to_thread(self._operation, account_id, status_only=True)
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
        except Exception:
            self._set_error(state, '签到状态查询失败')
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
            return dict(state)
        marker = (account_id, target_date)
        with self._state_guard:
            if marker in self._post_started:
                self._set_error(state, '签到结果未确认')
                return dict(state)
            self._post_started.add(marker)
        # Use a brand prefix even when host applications share an account store.
        ledger_id = 'trae-cn:' + account_id
        try:
            claimed = await asyncio.to_thread(self._attempt_ledger, ledger_id, target_date)
        except (OSError, sqlite3.Error):
            self._set_error(state, '签到结果未确认')
            return dict(state)
        if not claimed:
            self._set_error(state, '签到结果未确认')
            return dict(state)
        state.update(status='signing', checked=False, error=None, next_checkin_at=None)
        try:
            async with self._semaphore:
                result = await asyncio.to_thread(
                    self._operation, account_id, status_only=False,
                    before_claim=lambda: self._before_post_allowed(account_id, target_date, require_enabled))
        except asyncio.CancelledError:
            state.update(status='unknown', checked=None, error=None, next_checkin_at=None)
            raise
        except Exception:
            self._set_error(state, '签到结果未确认')
            return dict(state)
        action = result.get('action')
        if action in {'cancelled', 'already_checked_in', 'device_already_checked_in', 'disabled'}:
            try:
                await asyncio.to_thread(self._attempt_ledger, ledger_id, target_date, clear=True)
            except (OSError, sqlite3.Error):
                self._set_error(state, '签到结果未确认')
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
        self._log('trae_checkin_finished', account_id=account_id, date=target_date,
                  reason=reason, status=state['status'])
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
            {'event': event, **fields}, ensure_ascii=False), flush=True))
        try:
            asyncio.run(_run_scheduler(service))
        except KeyboardInterrupt:
            return 0
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f'Trae scheduler failed: {exc}')
        return 1
