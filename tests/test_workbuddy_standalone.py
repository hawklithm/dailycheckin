"""Offline verification of standalone WorkBuddy commands and shared accounts."""
import json
import sys

import httpx
import pytest

pytest.importorskip('buddy_agent_auth')
from buddy_agent_auth import AccountStore, CodeBuddyClient
from daily_checkin.workbuddy_cli import main


def test_list_status_and_execute_with_shared_store(tmp_path, monkeypatch, capsys):
    client = CodeBuddyClient(session_file=tmp_path / 'login.json')
    client._save_session({'auth': {'accessToken': 'synthetic-token', 'refreshToken': 'synthetic-refresh'},
                          'account': {'uid': 'synthetic-user'}, 'machineId': 'machine'})
    store = AccountStore(tmp_path / 'accounts')
    account_id = store.import_client(client)
    base = ['--accounts-dir', str(store.root)]
    assert main(base + ['list']) == 0
    assert json.loads(capsys.readouterr().out)[0]['id'] == account_id
    requests, signed = [], [False]
    async def upstream(request):
        requests.append(request)
        assert request.headers['Authorization'] == 'Bearer synthetic-token'
        if request.url.path.endswith('/daily-checkin'):
            signed[0] = True
            return httpx.Response(200, json={'code': 0, 'data': {}})
        return httpx.Response(200, json={'code': 0, 'data': {'active': True, 'today_checked_in': signed[0]}})
    real_client = httpx.AsyncClient
    monkeypatch.setattr('daily_checkin.workbuddy_billing.httpx.AsyncClient',
                        lambda **kwargs: real_client(transport=httpx.MockTransport(upstream), **kwargs))
    assert main(base + ['status', '--account', account_id]) == 0
    assert json.loads(capsys.readouterr().out)['checked'] is False
    assert main(base + ['execute', '--account', account_id]) == 0
    assert json.loads(capsys.readouterr().out)['checked'] is True
    assert sum(req.url.path.endswith('/daily-checkin') for req in requests) == 1
