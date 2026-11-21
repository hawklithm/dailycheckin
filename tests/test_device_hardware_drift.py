"""Hardware drift uses a single synthetic baseline and never accesses the host."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from trae2api import device_hardware as hw
from trae2api import debuglog


@pytest.fixture
def baseline(monkeypatch):
    monkeypatch.setattr(hw, '_baseline', None)
    calls = []
    def uuids():
        calls.append('read')
        return '33221100-5544-7766-8899-AABBCCDDEEFF', '33221100-5544-7766-8899-AABBCCDDEEFF'
    monkeypatch.setattr(hw, 'device_uuids', uuids)
    monkeypatch.setattr(hw, 'disk_serial', lambda: 'SN-123456')
    monkeypatch.setattr(hw, 'device_model', lambda: 'model')
    monkeypatch.setattr(hw, 'manufacturer', lambda: 'brand')
    monkeypatch.setattr(hw, 'cpu_brand', lambda: 'cpu')
    monkeypatch.setattr(hw, 'os_metadata', lambda: ('windows', 'Windows'))
    monkeypatch.setattr(hw.platform, 'version', lambda: '10.0')
    monkeypatch.setattr(hw, 'mac_address', lambda: '00-11-22-33-44-55')
    return calls


def test_unscoped_reads_use_real_snapshot_without_drift(baseline, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail('unscoped reads must not create or log drift')
    monkeypatch.setattr(hw, '_drift_serial', unexpected)
    monkeypatch.setattr(hw, '_drift_mac', unexpected)
    monkeypatch.setattr(debuglog, 'get_logger', unexpected)
    first, second = hw.Hardware.read_native(), hw.Hardware.read_native()
    assert baseline == ['read']
    assert first == second
    assert first.pc_serial == 'SN-123456' and first.mac == '00-11-22-33-44-55'
    assert first.pc_uuid == first.local_device_id == '33221100-5544-7766-8899-AABBCCDDEEFF'


def test_initialization_is_thread_safe(baseline, monkeypatch):
    class Logger:
        def info(self, line):
            pass
    monkeypatch.setattr(debuglog, 'get_logger', lambda: Logger())
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: hw.Hardware.read_native(), range(20)))
    assert baseline == ['read'] and len(results) == 20


def test_missing_or_unrecognized_values_are_not_invented():
    assert hw._drift_serial('') == ''
    assert hw._drift_mac('') == ''
    assert hw._drift_mac('unrecognized') == 'unrecognized'


def test_profiles_persist_per_account_and_reload_without_sampling(baseline, tmp_path, monkeypatch):
    from trae2api import app_storage
    storage = tmp_path / '.traeapi'
    storage.mkdir()
    monkeypatch.setattr(app_storage, 'root', lambda: storage)
    class Logger:
        def info(self, line):
            pass
    monkeypatch.setattr(debuglog, 'get_logger', lambda: Logger())
    first = hw.Hardware.for_account('user-a')
    other = hw.Hardware.for_account('user-b')
    assert first == hw.Hardware.read_native('user-a')
    assert first.pc_uuid != other.pc_uuid
    assert first.pc_uuid == first.local_device_id
    assert first.pc_uuid != '33221100-5544-7766-8899-AABBCCDDEEFF'
    assert first.model == other.model == 'model'
    assert first.os_version == other.os_version == 'Windows'
    monkeypatch.setattr(hw.Hardware, 'read_real', classmethod(lambda cls: pytest.fail('unexpected hardware read')))
    assert hw.Hardware.for_account('user-a') == first
    profiles = json.loads((storage / 'device_hardware.json').read_text(encoding='utf-8'))
    assert set(profiles) == {'user-a', 'user-b'}
    assert profiles['user-a']['pc_uuid'] == first.pc_uuid
    assert baseline == ['read']


def test_invalid_profiles_are_not_overwritten(tmp_path, monkeypatch):
    from trae2api import app_storage
    storage = tmp_path / '.traeapi'
    storage.mkdir()
    path = storage / 'device_hardware.json'
    path.write_text('{"user": {"pc_uuid": "bad"}}', encoding='utf-8')
    monkeypatch.setattr(app_storage, 'root', lambda: storage)
    with pytest.raises(ValueError, match='invalid account hardware profile'):
        hw.Hardware.for_account('user')
    assert json.loads(path.read_text()) == {'user': {'pc_uuid': 'bad'}}


def test_account_profile_used_for_registration_and_request(baseline, tmp_path, monkeypatch):
    import httpx
    from trae2api import app_storage
    from trae2api.aha_registration import Registration
    from trae2api.checkin import Account, checkin
    from trae2api.aha_tiny_storage import NativeTinyStorage
    storage = tmp_path / '.traeapi'
    storage.mkdir()
    monkeypatch.setattr(app_storage, 'root', lambda: storage)
    class Logger:
        def info(self, line):
            pass
    monkeypatch.setattr(debuglog, 'get_logger', lambda: Logger())
    registered = []
    activated = []
    monkeypatch.setattr('trae2api.aha_registration.register',
                        lambda client, hardware, version: registered.append(hardware) or Registration('123', '456', 'CN'))
    monkeypatch.setattr('trae2api.aha_registration.activate',
                        lambda client, registration, hardware, version, **kwargs: activated.append(hardware))
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(200, json={'enable': True, 'checked_in': False})
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        checkin(Account('token', 'initial', user_id='user'), client, status_only=True)
    profile = hw.Hardware.for_account('user')
    assert registered == activated == [profile]
    assert requests[0].headers['x-device-brand'] == profile.model
    assert requests[0].headers['x-os-version'] == profile.os_version
    assert NativeTinyStorage(storage / '123' / 'TinyStorage').load_device(profile.pc_uuid).device_id == '123'


@pytest.mark.parametrize('mode,expected_paths', [
    ('--status-only', ['/trae/api/v2/ug/checkin_credits/status']),
    ('--execute', ['/trae/api/v2/ug/checkin_credits/status',
                   '/trae/api/v2/ug/checkin_credits/claim',
                   '/trae/api/v2/ug/checkin_credits/status']),
])
def test_cli_modes_share_persisted_device_for_all_requests(baseline, tmp_path, monkeypatch, mode, expected_paths):
    import httpx
    from types import SimpleNamespace
    from trae2api import app_storage
    from trae2api.aha_registration import Registration
    from trae2api.checkin import main
    from trae2api.native_identity import NativeIdentity

    storage = tmp_path / '.traeapi'
    storage.mkdir()
    monkeypatch.setattr(app_storage, 'root', lambda: storage)
    class Logger:
        def info(self, line):
            pass
    monkeypatch.setattr(debuglog, 'get_logger', lambda: Logger())
    native = SimpleNamespace(user_id='user', token='token', device_id='original', user_region='CN',
                             ensure_current=lambda: None)
    monkeypatch.setattr(NativeIdentity, 'load', classmethod(lambda cls, **kwargs: native))
    registered, activated = [], []
    monkeypatch.setattr('trae2api.aha_registration.register',
                        lambda client, hardware, version: registered.append(hardware) or Registration('123', '456', 'CN'))
    monkeypatch.setattr('trae2api.aha_registration.activate',
                        lambda client, registration, hardware, version, **kwargs: activated.append(hardware))
    requests = []
    def reply(request):
        requests.append(request)
        path = request.url.path
        if path.endswith('/claim'):
            return httpx.Response(200, json={'code': 0})
        return httpx.Response(200, json={'enable': True, 'checked_in': len(requests) > 1})
    client = httpx.Client(transport=httpx.MockTransport(reply))
    monkeypatch.setattr('trae2api.checkin.httpx.Client', lambda **kwargs: client)
    assert main(['--native', '--device-id-source', 'get-device-id', mode]) == 0
    profile = hw.Hardware.for_account('user')
    assert registered == activated == [profile]
    assert [request.url.path for request in requests] == expected_paths
    assert all(request.headers['x-device-id'] == '123' for request in requests)
    assert all(request.headers['x-device-brand'] == profile.model for request in requests)
    assert all(request.headers['x-os-version'] == profile.os_version for request in requests)
    assert json.loads((storage / 'device_pair.json').read_text(encoding='utf-8')) == {'user': '123'}
