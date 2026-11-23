import json
import socket
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from trae2api.sandbox_lab import storage
from trae2api.sandbox_lab.__main__ import main
from trae2api.sandbox_lab.config import ExperimentConfig, local_config
from trae2api.sandbox_lab.fixtures import FixtureStore
from trae2api.sandbox_lab.mock_server import CAPABILITIES, running_mock
from trae2api.sandbox_lab.runner import run


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "OUTPUT_ROOT", tmp_path / "lab")
    return local_config(8765, str(tmp_path / "lab" / "runner"))


def test_dry_run_does_not_create_client_or_socket(cfg, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("dry run attempted network/client creation")
    monkeypatch.setattr(httpx, "Client", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    first = run(cfg)
    second = run(cfg)
    assert first["experiment_id"] != second["experiment_id"]
    assert first["requests_sent"] == second["requests_sent"] == 0
    assert first["planned_requests"] == 6
    assert first["source_kind"] == "offline_fixture"
    assert first["completion_status"] == "dry_run"
    assert all(x["registration"]["state"] == "not_run" for x in first["fixture_results"])
    assert json.loads(Path(first["report_path"]).read_text(encoding="utf-8")) == first


@pytest.mark.parametrize("budget,expected_requests,failed_stage", [(1, 1, "registration"), (2, 2, "activation"), (3, 3, "replay"), (4, 4, "registration")])
def test_budget_stops_all_subsequent_requests(cfg, budget, expected_requests, failed_stage):
    data = cfg.as_dict()
    data["max_requests"] = budget
    seen = []
    def handler(request):
        seen.append(request.url.path)
        if len(seen) == 1:
            body = CAPABILITIES
        elif request.url.path.endswith("activate"):
            body = {"accepted": True, "activated": True}
        else:
            body = {"accepted": True, "sandbox_device_id": "lab-d", "sandbox_install_id": "lab-i"}
        return httpx.Response(200, json=body)
    report = run(ExperimentConfig.from_dict(data), execute=True, transport=httpx.MockTransport(handler))
    assert report["requests_sent"] == len(seen) == expected_requests
    assert report["completion_status"] == "budget_exhausted"
    assert any(x[failed_stage]["state"] == "budget_exhausted" for x in report["fixture_results"])


@pytest.mark.parametrize("stage", ["register", "activate"])
def test_timeout_unknown_no_retry_or_followup(cfg, stage):
    seen = []
    def handler(request):
        seen.append(request.url.path)
        if request.url.path.endswith("capabilities"):
            return httpx.Response(200, json=CAPABILITIES)
        if request.url.path.endswith(stage):
            raise httpx.ReadTimeout("secret-message-must-not-leak", request=request)
        return httpx.Response(200, json={"accepted": True, "sandbox_device_id": "lab-d", "sandbox_install_id": "lab-i"})
    report = run(cfg, execute=True, transport=httpx.MockTransport(handler))
    assert report["completion_status"] == "failed"
    assert report["requests_sent"] == len(seen) == (2 if stage == "register" else 3)
    observation = report["fixture_results"][0]["registration" if stage == "register" else "activation"]
    assert observation["state"] == "network_error"
    assert observation["outcome_unknown"] is True
    assert "secret-message" not in json.dumps(report)


def test_handshake_failure_never_posts(cfg):
    seen = []
    def handler(request):
        seen.append(request.method)
        return httpx.Response(200, json={**CAPABILITIES, "rewards_enabled": True})
    report = run(cfg, execute=True, transport=httpx.MockTransport(handler))
    assert seen == ["GET"]
    assert report["capability"]["label"] == "capability_mismatch"


def test_real_loopback_end_to_end_persistence_replay_isolation(cfg, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://192.0.2.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://192.0.2.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    with running_mock() as mock:
        config = local_config(mock.server_port, str(cfg.output_directory))
        first = run(config, execute=True)
        assert first["completion_status"] == "passed"
        assert first["requests_sent"] == mock.state.requests == 6
        a, b, invalid = first["fixture_results"]
        assert a["replay"]["state"] == "accepted"
        assert a["activation"]["state"] == b["activation"]["state"] == "accepted"
        assert b["same_mock_physical_as_first"] is False
        assert invalid["validation"]["state"] == "rejected"
        assert invalid["registration"]["state"] == "not_run"
        assert len(mock.state.registrations) == len(mock.state.activated) == 2
        profile = cfg.output_directory / "profiles/lab-physical-h1-I1.installation.json"
        before = profile.read_bytes()
        second = run(config, execute=True)
        assert second["completion_status"] == "passed"
        assert profile.read_bytes() == before
        assert second["experiment_id"] != first["experiment_id"]
        assert len(mock.state.registrations) == 4
        assert first["source_kind"] == "local_mock"
        assert first["account_binding"] == first["online_checkin"] == first["provider_test"] == "not_run"


def test_renamed_fixture_uses_same_mock_physical_group(cfg):
    with running_mock() as mock:
        data = local_config(mock.server_port, str(cfg.output_directory)).as_dict()
        data["fixture_ids"] = ["fixture-a", "fixture-a-display"]
        report = run(ExperimentConfig.from_dict(data), execute=True)
        assert report["completion_status"] == "passed"
        assert report["fixture_results"][1]["same_mock_physical_as_first"] is True


@pytest.mark.parametrize("change_replay", [True, False])
def test_replay_change_or_cross_fixture_id_collision_fails(cfg, change_replay):
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        if request.url.path.endswith("capabilities"):
            return httpx.Response(200, json=CAPABILITIES)
        if request.url.path.endswith("activate"):
            return httpx.Response(200, json={"accepted": True, "activated": True})
        device = "lab-changed" if change_replay and calls == 4 else "lab-same"
        return httpx.Response(200, json={"accepted": True, "sandbox_device_id": device, "sandbox_install_id": "lab-install"})
    report = run(cfg, execute=True, transport=httpx.MockTransport(handler))
    assert report["completion_status"] == "failed"
    assert calls == (4 if change_replay else 5)
    assert report["fixture_results"][0 if change_replay else 1]["replay" if change_replay else "registration"]["state"] == "protocol_error"


def test_cli_offline_and_config_failure_no_secret_echo(cfg, tmp_path, capsys, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline CLI created a network client")
    monkeypatch.setattr(httpx, "Client", forbidden)
    assert main(["fixtures", "--output-directory", str(cfg.output_directory)]) == 0
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg.as_dict()))
    assert main(["run", "--config", str(path)]) == 0
    bad = cfg.as_dict()
    bad["base_url"] = "http://secret-token@127.0.0.1:8765"
    path.write_text(json.dumps(bad))
    assert main(["run", "--config", str(path), "--execute"]) == 2
    assert "secret-token" not in capsys.readouterr().out


@pytest.mark.parametrize("phase", ["capabilities", "register", "activate"])
def test_redirect_stops_at_any_stage_without_secret_echo(cfg, phase):
    seen = []
    def handler(request):
        seen.append(request.url.path)
        if request.url.path.endswith(phase):
            return httpx.Response(307, headers={"Location": "https://secret-redirect.invalid"},
                                  json={"token": "secret-response-must-not-appear"})
        if request.url.path.endswith("capabilities"):
            return httpx.Response(200, json=CAPABILITIES)
        return httpx.Response(200, json={"accepted": True, "sandbox_device_id": "lab-d", "sandbox_install_id": "lab-i"})
    report = run(cfg, execute=True, transport=httpx.MockTransport(handler))
    assert report["completion_status"] == "failed"
    assert len(seen) == {"capabilities": 1, "register": 2, "activate": 3}[phase]
    assert "secret-" not in json.dumps(report)


def test_duplicate_persisted_installation_labels_are_rejected(cfg):
    store = FixtureStore(cfg.output_directory)
    first = store.installation("lab-physical-h1", "I1")
    second = store.installation("lab-physical-h1", "I2")
    second["machine_id"] = first["machine_id"]
    storage.atomic_json(cfg.output_directory / "profiles/lab-physical-h1-I2.installation.json", second)
    with pytest.raises(ValueError, match="remain distinct"):
        run(cfg)


def test_local_package_does_not_import_production_hardware_or_auth():
    script = """
import builtins
original = builtins.__import__
denied = {'login', 'auth', 'native_identity', 'device_hardware', 'aha_registration', 'credential_decrypt', 'checkin', 'login_identity'}
def checked(name, globals=None, locals=None, fromlist=(), level=0):
    if name.startswith('trae2api.') and name.split('.')[1] in denied:
        raise AssertionError('production import: ' + name)
    if level and globals and str(globals.get('__package__', '')).startswith('trae2api.sandbox_lab'):
        if level > 1 or name.split('.')[0] in denied:
            raise AssertionError('production relative import')
    return original(name, globals, locals, fromlist, level)
builtins.__import__ = checked
import trae2api.sandbox_lab.__main__
import trae2api.sandbox_lab.runner
import trae2api.sandbox_lab.mock_server
import trae2api.sandbox_lab.binding_runner
import trae2api.sandbox_lab.keys
print('isolated imports passed')
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "isolated imports passed" in result.stdout
