"""Standalone tests for migrated WorkBuddy HTTP and projection adapters."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from daily_checkin import workbuddy_billing
from daily_checkin.workbuddy_api import create_legacy_router, safe_checkin


@pytest.mark.parametrize('method,path,upstream', [
    ('GET', '/v1/checkin-status', '/v2/billing/meter/checkin-activity-status'),
    ('POST', '/v1/checkin-status', '/v2/billing/meter/checkin-activity-status'),
    ('POST', '/v1/checkin', '/v2/billing/meter/daily-checkin'),
])
def test_standalone_router_preserves_legacy_passthrough(monkeypatch, method, path, upstream):
    class Client:
        def build_url(self, endpoint):
            return 'https://example.test' + endpoint
        def auth_headers(self):
            return {'Authorization': 'Bearer synthetic'}
    seen = []
    async def handler(request):
        seen.append(request)
        return httpx.Response(429, content=b'{"code":429}', headers={'Retry-After': '20'})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(workbuddy_billing.httpx, 'AsyncClient',
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    state = SimpleNamespace(client=Client(), ensure_auth=lambda: None)
    app = FastAPI()
    app.include_router(create_legacy_router(lambda: state, lambda *args, **kwargs: None))
    with TestClient(app) as client:
        response = client.request(method, path)
    assert response.status_code == 429 and response.content == b'{"code":429}'
    assert response.headers['retry-after'] == '20'
    assert len(seen) == 1 and seen[0].method == 'POST' and seen[0].url.path == upstream


def test_safe_projection_does_not_expose_arbitrary_fields():
    value = safe_checkin({'date': '2026-11-21', 'status': 'error', 'checked': False,
                          'error': 'secret-token', 'token': 'secret-token',
                          'last_checked_at': float('inf'), 'next_checkin_at': True})
    assert value['error'] == '签到状态查询失败'
    assert value['last_checked_at'] is None and value['next_checkin_at'] is None
    assert 'secret-token' not in repr(value)
