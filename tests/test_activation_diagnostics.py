import json

import httpx
import pytest

from trae2api import debuglog
from trae2api.aha_registration import Registration, activate
from trae2api.device_hardware import Hardware


@pytest.fixture
def records(monkeypatch):
    result = []
    class Logger:
        def info(self, line):
            result.append(json.loads(line))
    monkeypatch.setattr(debuglog, 'get_logger', lambda: Logger())
    return result


def run_activation(response):
    hardware = Hardware('secret-hardware', 'secret-serial', '', '', '', '', '', '')
    registration = Registration('secret-device', 'secret-install', 'CN')
    with httpx.Client(transport=httpx.MockTransport(lambda request: response)) as client:
        activate(client, registration, hardware, '3.4.20')


@pytest.mark.parametrize('response,expected,raises', [
    (httpx.Response(200, json={'message': 'success', 'data': {'is_activated': True}}),
     {'http_status': 200, 'message_state': 'success', 'data_type': 'dict',
      'activation_type': 'bool', 'activation_value': True}, False),
    (httpx.Response(200, json={'message': 'secret-token', 'data': {'is_activated': '1', 'token': 'secret-token'}, 'code': 9}),
     {'http_status': 200, 'message_state': 'other_string', 'activation_type': 'str',
      'activation_value': '1', 'code': 9}, True),
    (httpx.Response(200, json={'message': 'success', 'data': {}}),
     {'http_status': 200, 'activation_type': 'missing'}, True),
    (httpx.Response(503, text='secret-token'),
     {'http_status': 503, 'response_type': 'invalid_json'}, True),
])
def test_activation_logs_only_allowlisted_diagnostics(records, response, expected, raises):
    if raises:
        with pytest.raises(ValueError):
            run_activation(response)
    else:
        run_activation(response)
    assert len(records) == 1
    assert records[0]['kind'] == 'device_activation'
    assert all(records[0].get(key) == value for key, value in expected.items())
    log = json.dumps(records)
    assert 'secret-' not in log


def test_network_error_logs_only_exception_type(records):
    hardware = Hardware('secret-hardware', 'secret-serial', '', '', '', '', '', '')
    def fail(request):
        raise httpx.ConnectError('secret-token', request=request)
    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(ValueError, match='ConnectError'):
            activate(client, Registration('secret-device', 'secret-install', 'CN'), hardware, '3.4.20')
    assert records == [{'kind': 'device_activation', 'http_status': None, 'network_error': 'ConnectError'}]


def test_native_completion_accepts_missing_data_but_strict_login_does_not(records):
    hardware = Hardware('uuid', 'serial', '', '', '', '', '', '')
    registration = Registration('123', '456', 'CN')
    with httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={'message': 'success'}))) as client:
        activate(client, registration, hardware, '3.4.20', require_confirmation=False)
        with pytest.raises(ValueError, match='not confirmed'):
            activate(client, registration, hardware, '3.4.20')
    assert [entry['data_type'] for entry in records] == ['missing', 'missing']


def test_native_completion_rejects_non_200(records):
    hardware = Hardware('uuid', 'serial', '', '', '', '', '', '')
    with httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(503, json={'message': 'success'}))) as client:
        with pytest.raises(ValueError, match='HTTP 503'):
            activate(client, Registration('123', '456', 'CN'), hardware, '3.4.20', require_confirmation=False)
