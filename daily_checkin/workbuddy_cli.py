"""Standalone WorkBuddy account and activity commands."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

from .workbuddy import AccountCheckinService
from .workbuddy_travel import WorkBuddyTravelService


class _Manager:
    def __init__(self, store, *, enabled=False):
        self.store = store
        self.enabled = enabled

    def has_account(self, account_id):
        return any(row.get('id') == account_id for row in self.store.list_accounts())

    def get_settings(self):
        return {'auto_checkin_enabled': self.enabled}


async def _run_action(store, account_id, action):
    service = AccountCheckinService(_Manager(store))
    try:
        if action == 'status':
            return await service.check_status(account_id)
        return await service.check_in(account_id)
    finally:
        await service.close()


async def _run_scheduler(store):
    service = AccountCheckinService(_Manager(store, enabled=True))
    try:
        await service.start()
        await asyncio.Event().wait()
    finally:
        await service.close()


async def _travel_action(store, action, account_id=None):
    service = WorkBuddyTravelService(store)
    try:
        if action == 'status':
            return await service.status(account_id)
        if action == 'execute':
            return await service.run_account(account_id)
        if action in ('enable', 'disable'):
            return service.set_enabled(action == 'enable')
        service.configure_logging(lambda event, **fields: print(json.dumps(
            {'timestamp': datetime.now(timezone.utc).isoformat(), 'event': event, **fields},
            ensure_ascii=False), flush=True))
        service.set_enabled(True)
        await service.start()
        await asyncio.Event().wait()
    finally:
        await service.close()


def main(argv=None):
    parser = argparse.ArgumentParser(prog='daily-checkin workbuddy', description='WorkBuddy accounts and activities')
    parser.add_argument('--accounts-dir', help='account store directory (default: ~/.workbuddy2api/accounts)')
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('list', help='list associated accounts')
    login = commands.add_parser('login', help='associate an account through browser login')
    login.add_argument('--global', dest='global_mode', action='store_true')
    login.add_argument('--no-browser', action='store_true')
    login.add_argument('--timeout', type=int, default=300)
    for action in ('status', 'execute'):
        command = commands.add_parser(action)
        command.add_argument('--account', required=True, help='account ID from list')
    commands.add_parser('schedule', help='run automatic daily check-in until stopped')
    travel = commands.add_parser('travel', help='WorkBuddy CN cat travel')
    travel_commands = travel.add_subparsers(dest='travel_action', required=True)
    for action in ('status', 'execute'):
        command = travel_commands.add_parser(action)
        command.add_argument('--account', required=True, help='account ID from list')
    for action in ('enable', 'disable', 'schedule'):
        travel_commands.add_parser(action)
    args = parser.parse_args(argv)
    try:
        from buddy_agent_auth import AccountStore, CodeBuddyClient, CodeBuddyError
        from buddy_agent_auth.backend_profile import resolve_backend
    except ImportError:
        parser.exit(1, 'WorkBuddy support requires daily-checkin[workbuddy].\n')
    try:
        store = AccountStore(args.accounts_dir)
        if args.action == 'list':
            print(json.dumps(store.list_accounts(), ensure_ascii=False))
        elif args.action == 'login':
            with tempfile.TemporaryDirectory(prefix='daily-checkin-login-') as temporary:
                backend = resolve_backend(global_mode=args.global_mode,
                    session_file=Path(temporary) / 'session.json', environment={})
                client = CodeBuddyClient(backend=backend)
                client.login(open_browser=not args.no_browser, timeout=args.timeout)
                account_id = store.import_client(client)
            print(json.dumps({'account_id': account_id, 'status': 'succeeded'}))
        elif args.action == 'travel':
            try:
                result = asyncio.run(_travel_action(store, args.travel_action, getattr(args, 'account', None)))
            except KeyboardInterrupt:
                return 0
            if result is not None:
                print(json.dumps(result, ensure_ascii=False))
                return 1 if result.get('ok') is False else 0
        elif args.action == 'schedule':
            try:
                asyncio.run(_run_scheduler(store))
            except KeyboardInterrupt:
                return 0
        else:
            result = asyncio.run(_run_action(store, args.account, args.action))
            print(json.dumps(result, ensure_ascii=False))
            return 1 if result.get('status') == 'error' else 0
        return 0
    except (CodeBuddyError, OSError, ValueError) as exc:
        print(f'WorkBuddy operation failed: {exc}')
        return 1
