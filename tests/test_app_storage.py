import json

import httpx
import pytest

from trae2api import app_storage
from trae2api.aha_device_cache import DeviceRecord
from trae2api.checkin import Account, checkin
from trae2api.login_identity import IdentityStore, LoginIdentity, new_key
from trae2api.aha_tiny_storage import NativeTinyStorage


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    storage = tmp_path / '.traeapi'
    storage.mkdir()
    monkeypatch.setattr(app_storage, 'root', lambda: storage)


def test_registered_devices_get_separate_native_compatible_storage(tmp_path):
    for number in ('123', '456'):
        record = DeviceRecord(number, '789', 'hardware')
        identity = LoginIdentity('machine', new_key(), number, '789', True, False,
                                 'CN', 'hardware', record.encoded())
        IdentityStore(tmp_path / (number + '.json')).save(identity)
        path = tmp_path / '.traeapi' / number / 'TinyStorage'
        assert NativeTinyStorage(path).load_device('hardware') == record
    assert (tmp_path / '.traeapi' / '123' / 'TinyStorage').exists()


def test_first_checkin_registers_then_reuses_binding(tmp_path, monkeypatch):
    from trae2api.aha_registration import Registration
    from trae2api.device_hardware import Hardware
    hardware = Hardware('hardware', '', '', '', '', 'windows', '', '', '')
    calls = []
    monkeypatch.setattr(Hardware, 'for_account', classmethod(lambda cls, user_id: hardware))
    monkeypatch.setattr('trae2api.aha_registration.register',
                        lambda client, hw, version: calls.append('register') or Registration('123', '456', 'CN'))
    monkeypatch.setattr('trae2api.aha_registration.activate',
                        lambda client, registration, hw, version, **kwargs: calls.append('activate'))
    requests = []
    def handle(request):
        requests.append(request.headers['x-device-id'])
        return httpx.Response(200, json={'enable': True, 'checked_in': False})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        checkin(Account('token', 'old', user_id='account'), client, status_only=True)
        assert requests == ['123']
        assert NativeTinyStorage(tmp_path / '.traeapi' / '123' / 'TinyStorage').load_device('hardware') == DeviceRecord('123', '456', 'hardware')
        pairs_file = tmp_path / '.traeapi' / 'device_pair.json'
        pairs_file.write_text(json.dumps({'account': '123', 'other': '456'}), encoding='utf-8')
        checkin(Account('token', '789', user_id='account'), client, status_only=True)
    assert calls == ['register', 'activate']
    assert requests == ['123', '123']
    pairs = json.loads((tmp_path / '.traeapi' / 'device_pair.json').read_text(encoding='utf-8'))
    assert pairs == {'account': '123', 'other': '456'}


def test_registration_failure_does_not_bind(tmp_path, monkeypatch):
    from trae2api.device_hardware import Hardware
    monkeypatch.setattr(Hardware, 'for_account', classmethod(lambda cls, user_id: object()))
    def fail(*args):
        raise ValueError('registration failed')
    monkeypatch.setattr('trae2api.aha_registration.register', fail)
    with httpx.Client(transport=httpx.MockTransport(lambda request: pytest.fail('unexpected request'))) as client:
        with pytest.raises(ValueError, match='registration failed'):
            checkin(Account('token', 'old', user_id='account'), client, status_only=True)
    assert not (tmp_path / '.traeapi' / 'device_pair.json').exists()


def test_bad_pair_file_is_not_overwritten(tmp_path):
    path = tmp_path / '.traeapi' / 'device_pair.json'
    path.write_text('broken', encoding='utf-8')
    from trae2api.device_hardware import Hardware
    from unittest.mock import patch
    with patch.object(Hardware, 'for_account', return_value=object()), pytest.raises(ValueError):
        app_storage.resolve_pair('account', '123', None, '')
    assert path.read_text(encoding='utf-8') == 'broken'


def test_missing_user_id_rejected():
    with pytest.raises(ValueError, match='userId'):
        app_storage.resolve_pair('', '123', None, '')


def test_storage_override_is_used_without_touching_home(tmp_path, monkeypatch):
    monkeypatch.undo()
    from trae2api import app_storage
    target = tmp_path / 'chosen'
    monkeypatch.setenv('TRAE2API_HOME', str(target))
    monkeypatch.setattr(app_storage.Path, 'home', lambda: pytest.fail('home must not be accessed'))
    assert app_storage.root() == target
    assert target.is_dir()


def test_storage_falls_back_when_profile_dirs_are_inaccessible(tmp_path, monkeypatch, capsys):
    monkeypatch.undo()
    from trae2api import app_storage
    from pathlib import Path
    home, alternate = tmp_path / 'home', tmp_path / 'alternate'
    project = tmp_path / 'project'
    (project / 'trae2api').mkdir(parents=True)
    monkeypatch.delenv('TRAE2API_HOME', raising=False)
    monkeypatch.setattr(app_storage, '_fallback_project_root', project)
    monkeypatch.setattr(app_storage.Path, 'home', lambda: home)
    monkeypatch.setattr(app_storage, '_python_profile_home', lambda _: alternate)
    original_mkdir = Path.mkdir
    def mkdir(self, *args, **kwargs):
        if self in (home / '.traeapi', alternate / '.traeapi'):
            raise PermissionError('denied')
        return original_mkdir(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'mkdir', mkdir)
    monkeypatch.setattr(app_storage, '_reported_fallbacks', set())
    expected = project / '.traeapi'
    assert app_storage.root() == expected
    assert app_storage.root() == expected
    assert capsys.readouterr().err.count('not writable') == 1


def test_override_permission_error_is_not_silently_redirected(tmp_path, monkeypatch):
    monkeypatch.undo()
    from trae2api import app_storage
    from pathlib import Path
    target = tmp_path / 'unwritable'
    monkeypatch.setenv('TRAE2API_HOME', str(target))
    original_mkdir = Path.mkdir
    def mkdir(self, *args, **kwargs):
        if self == target:
            raise PermissionError('denied')
        return original_mkdir(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'mkdir', mkdir)
    with pytest.raises(PermissionError):
        app_storage.root()


@pytest.mark.parametrize('bound', [False, True])
def test_native_account_device_source_works_without_native_device_records(tmp_path, monkeypatch, bound):
    from trae2api.aha_registration import Registration
    from trae2api.device_hardware import Hardware
    from trae2api.checkin import main
    native = tmp_path / 'native'
    (native / 'User/globalStorage').mkdir(parents=True)
    auth = {'userId': 'user', 'token': 'token', 'account': {'scope': 'marscode'}}
    (native / 'User/globalStorage/storage.json').write_text(json.dumps({'iCubeAuthInfo://icube.cloudide': json.dumps(auth)}))
    monkeypatch.setenv('TRAE2API_USER_DATA', str(native))
    monkeypatch.setattr('trae2api.native_identity.decrypt_value', lambda value: value)
    hardware = Hardware('uuid', 'serial', 'profile-model', 'brand', 'cpu', 'windows', 'profile-os', '10', '02-11-22-33-44-55')
    monkeypatch.setattr(Hardware, 'for_account', classmethod(lambda cls, user_id: hardware))
    if bound:
        (tmp_path / '.traeapi' / 'device_pair.json').write_text(json.dumps({'user': '111'}))
    registrations = []
    monkeypatch.setattr('trae2api.aha_registration.register',
                        lambda client, hw, version: registrations.append(hw) or Registration('222', '333', 'CN'))
    monkeypatch.setattr('trae2api.aha_registration.activate', lambda *args, **kwargs: None)
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={'enable': True, 'checked_in': False})
    client_class = httpx.Client
    monkeypatch.setattr('trae2api.checkin.httpx.Client',
                        lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs))
    assert main(['--native', '--device-id-source', 'get-device-id', '--status-only']) == 0
    assert seen[0].headers['x-device-id'] == ('111' if bound else '222')
    assert seen[0].headers['x-device-brand'] == 'profile-model'
    assert len(registrations) == (0 if bound else 1)
    assert not (native / 'logs').exists()


def test_failed_activation_reuses_pending_registration(tmp_path, monkeypatch):
    from trae2api.aha_registration import Registration
    from trae2api.device_hardware import Hardware
    hardware = Hardware('hardware', '', 'model', '', '', 'windows', '', '', '')
    monkeypatch.setattr(Hardware, 'for_account', classmethod(lambda cls, user_id: hardware))
    registered, activated, requests = [], [], []
    monkeypatch.setattr('trae2api.aha_registration.register',
                        lambda client, hw, version: registered.append(hw) or Registration('123', '456', 'CN'))
    def activate(client, registration, hw, version, *, require_confirmation):
        activated.append((registration, hw, require_confirmation))
        if len(activated) == 1:
            raise ValueError('activation failed')
    monkeypatch.setattr('trae2api.aha_registration.activate', activate)
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'enable': True, 'checked_in': False})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match='activation failed'):
            checkin(Account('token', '', user_id='account'), client, status_only=True)
        assert not (tmp_path / '.traeapi' / 'device_pair.json').exists()
        pending = json.loads((tmp_path / '.traeapi' / 'device_pending.json').read_text(encoding='utf-8'))
        assert pending['account']['device_id'] == '123'
        checkin(Account('token', '', user_id='account'), client, status_only=True)
    assert len(registered) == 1 and len(activated) == 2
    assert all(item[0].device_id == '123' and item[1] == hardware and item[2] is False for item in activated)
    assert requests[0].headers['x-device-id'] == '123'
    assert json.loads((tmp_path / '.traeapi' / 'device_pending.json').read_text(encoding='utf-8')) == {}
