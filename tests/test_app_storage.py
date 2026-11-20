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
                        lambda client, registration, hw, version: calls.append('activate'))
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
    monkeypatch.setattr(app_storage, '__file__', str(project / 'trae2api' / 'app_storage.py'))
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
