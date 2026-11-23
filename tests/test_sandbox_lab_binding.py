from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import subprocess
import sys
import uuid

import httpx
import pytest

from trae2api.sandbox_lab import keys, storage
from trae2api.sandbox_lab.binding_client import BindingClient
from trae2api.sandbox_lab.binding_runner import run_binding
from trae2api.sandbox_lab.client import LabFailure
from trae2api.sandbox_lab.config import ExperimentConfig, local_config
from trae2api.sandbox_lab.fixtures import DeviceFixture, FixtureStore, attributes_for
from trae2api.sandbox_lab.mock_server import CAPABILITIES, MockState, running_mock


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "OUTPUT_ROOT", tmp_path / "lab")
    return local_config(8765, str(tmp_path / "lab" / "binding"), scenario="binding_quota")


@pytest.fixture
def lab(cfg):
    clock = [datetime(2026, 11, 20, 15, 59, 30, tzinfo=timezone.utc).timestamp()]
    state = MockState(clock=lambda: clock[0])
    def handler(request):
        path = request.url.path
        if path == "/lab/capabilities":
            return httpx.Response(200, json=CAPABILITIES)
        body = json.loads(request.content)
        methods = {"/lab/register": state.register, "/lab/activate": state.activate,
                   "/lab/binding-challenge": state.binding.challenge, "/lab/bind": state.binding.bind}
        status, response = (methods[path](body) if path in methods else state.binding.protected(path, body))
        return httpx.Response(status, json=response)
    store = FixtureStore(cfg.output_directory)
    client = BindingClient(cfg, store, transport=httpx.MockTransport(handler), clock=lambda: clock[0])
    experiment = "lab-experiment-test-" + uuid.uuid4().hex
    client.capabilities()
    registrations = []
    for name in cfg.fixture_ids:
        reg = client.register(experiment, DeviceFixture(name, attributes_for(name)))
        client.activate(experiment, reg)
        registrations.append(reg)
    first = store.installation("lab-physical-h1", "I1")
    second = store.installation("lab-physical-h1", "I2")
    try:
        yield client, state, store, registrations, first, second, experiment, clock
    finally:
        client.close()


def challenge_body(client, experiment, registration, installation, account="lab-account-a"):
    return {"experiment_id": experiment, "app_id": client.config.app_id, "account_id": account,
            "sandbox_device_id": registration.device_id, "sandbox_install_id": registration.install_id,
            "machine_id": installation["machine_id"], "key_id": installation["key_id"],
            "public_key_pem": installation["public_key_pem"]}


def dispatch(state, request):
    if request.url.path == "/lab/capabilities":
        return httpx.Response(200, json=CAPABILITIES)
    body = json.loads(request.content)
    methods = {"/lab/register": state.register, "/lab/activate": state.activate,
               "/lab/binding-challenge": state.binding.challenge, "/lab/bind": state.binding.bind}
    status, response = (methods[request.url.path](body) if request.url.path in methods
                        else state.binding.protected(request.url.path, body))
    return httpx.Response(status, json=response)


def test_key_persistence_and_cross_process_signing(cfg):
    store = FixtureStore(cfg.output_directory)
    meta = store.installation("lab-physical-h1", "I1")
    assert meta["schema_version"] == 2 and meta["key_kind"] == "ecdsa_p256"
    assert store.installation("lab-physical-h1", "I1") == meta
    payload = {"synthetic": True, "operation": "persistence-test"}
    sig = store.sign(meta, "/lab/bind", payload)
    assert keys.verify(meta["public_key_pem"], "/lab/bind", payload, sig)
    assert not keys.verify(meta["public_key_pem"], "/lab/checkin/claim", payload, sig)
    assert not keys.verify(meta["public_key_pem"], "/lab/bind", {**payload, "synthetic": False}, sig)
    script = """
import json,sys
from pathlib import Path
from trae2api.sandbox_lab import storage
from trae2api.sandbox_lab.fixtures import FixtureStore
storage.OUTPUT_ROOT=Path(sys.argv[1])
s=FixtureStore(Path(sys.argv[2]))
m=s.installation('lab-physical-h1','I1')
print(json.dumps({'key_id':m['key_id'],'signature':s.sign(m,'/lab/bind',{'synthetic':True,'operation':'persistence-test'})}))
"""
    result = subprocess.run([sys.executable, "-c", script, str(storage.OUTPUT_ROOT), str(cfg.output_directory)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, "child key loading failed"
    second = json.loads(result.stdout)
    assert second["key_id"] == meta["key_id"]
    assert keys.verify(meta["public_key_pem"], "/lab/bind", payload, second["signature"])
    assert "PRIVATE KEY" not in result.stdout


def test_legacy_installation_migrates_preserving_machine_label(cfg):
    store = FixtureStore(cfg.output_directory)
    legacy = {"schema_version": 1, "synthetic": True, "physical_key": "lab-physical-h1", "installation_id": "I1",
              "machine_id": "lab-machine-" + uuid.uuid4().hex, "key_label": "lab-key-label-" + uuid.uuid4().hex,
              "key_kind": "synthetic_label_no_signature"}
    path = cfg.output_directory / "profiles/lab-physical-h1-I1.installation.json"
    storage.atomic_json(path, legacy)
    meta = store.installation("lab-physical-h1", "I1")
    assert meta["machine_id"] == legacy["machine_id"] and meta["key_label"] == legacy["key_label"]
    assert meta["key_kind"] == "ecdsa_p256"
    archives = list((path.parent / "history").glob("*.json"))
    assert len(archives) == 1 and json.loads(archives[0].read_text()) == legacy
    assert store.installation("lab-physical-h1", "I1") == meta
    assert len(list((path.parent / "history").glob("*.json"))) == 1


def test_rebuild_retains_old_key_and_rotates_identity(cfg):
    store = FixtureStore(cfg.output_directory)
    old = store.installation("lab-physical-h1", "I2")
    old_signature = store.sign(old, "/lab/bind", {})
    new = store.rebuild_installation("lab-physical-h1", "I2")
    assert old["physical_key"] == new["physical_key"]
    assert old["key_id"] != new["key_id"] and old["machine_id"] != new["machine_id"]
    assert keys.verify(old["public_key_pem"], "/lab/bind", {}, old_signature)
    assert keys.verify(new["public_key_pem"], "/lab/bind", {}, store.sign(new, "/lab/bind", {}))
    assert len(list(store.directory.glob("*.p256.secret"))) == 2


def test_failed_rebuild_publication_keeps_old_identity_usable(cfg, monkeypatch):
    store = FixtureStore(cfg.output_directory)
    before = store.installation("lab-physical-h1", "I1")
    original = keys.atomic_json
    def fail_publish(path, value, **kwargs):
        if path.name.endswith(".installation.json"):
            raise OSError("simulated metadata publication failure")
        return original(path, value, **kwargs)
    monkeypatch.setattr(keys, "atomic_json", fail_publish)
    with pytest.raises(OSError):
        store.rebuild_installation("lab-physical-h1", "I1")
    assert store.installation("lab-physical-h1", "I1") == before
    assert keys.verify(before["public_key_pem"], "/lab/bind", {}, store.sign(before, "/lab/bind", {}))


@pytest.mark.parametrize("failure", ["missing", "corrupt", "different_key"])
def test_private_key_failure_never_silently_regenerates(cfg, failure):
    store = FixtureStore(cfg.output_directory)
    meta = store.installation("lab-physical-h1", "I1")
    path = keys._secret_path(store.directory, meta)
    public_path = store.directory / "lab-physical-h1-I1.installation.json"
    before = public_path.read_bytes()
    if failure == "missing":
        path.unlink()
    elif failure == "corrupt":
        path.write_text('{"schema_version":1,"private_key_pem":"invalid"}')
    else:
        other = store.installation("lab-physical-h1", "I2")
        path.write_bytes(keys._secret_path(store.directory, other).read_bytes())
    with pytest.raises((OSError, ValueError)):
        store.installation("lab-physical-h1", "I1")
    assert public_path.read_bytes() == before


def test_public_key_algorithm_and_fingerprint_are_checked(lab):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    client, state, store, regs, first, second, exp, clock = lab
    body = challenge_body(client, exp, regs[0], first)
    for change in [{"public_key_pem": "not a public key"}, {"key_id": second["key_id"]}]:
        assert state.binding.challenge({**body, **change})[0] == 400
    key = ec.generate_private_key(ec.SECP384R1()).public_key()
    pem = key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    assert state.binding.challenge({**body, "public_key_pem": pem})[0] == 400


def test_account_switch_and_rebuild_cannot_reset_device_quota(lab):
    client, state, store, regs, first, second, exp, clock = lab
    a = client.bind(exp, regs[0], first, "lab-account-a")
    assert client.claim(a)["granted"] is True
    b = client.bind(exp, regs[0], first, "lab-account-b")
    status = client.status(b)
    assert status["checked_in"] is False and status["did_checked_in"] is True
    assert client.claim(b)["reason"] == "device_daily_limit"
    rebuilt = store.rebuild_installation("lab-physical-h1", "I2")
    b2 = client.bind(exp, regs[1], rebuilt, "lab-account-b")
    assert client.claim(b2)["reason"] == "device_daily_limit"
    assert client.ledger(a)["count"] == 1
    assert client.claim(a)["reason"] == "account_daily_limit"
    assert len(state.binding.ledger) == 1


def test_claim_is_rejected_for_account_on_a_second_device(lab):
    client, state, store, regs, first, second, exp, clock = lab
    a = client.bind(exp, regs[0], first, "lab-account-a")
    assert client.claim(a)["granted"]
    other = store.installation("lab-physical-h2", "I1")
    a2 = client.bind(exp, regs[2], other, "lab-account-a")
    assert client.status(a2)["did_checked_in"] is False
    assert client.claim(a2)["reason"] == "account_daily_limit"
    assert len(state.binding.ledger) == 1


@pytest.mark.parametrize("change", ["device", "account", "unsigned_tamper", "other_key", "cross_path", "experiment", "stale"])
def test_signed_session_binding_rejects_mismatch_and_tampering(lab, change):
    client, state, store, regs, first, second, exp, clock = lab
    session = client.bind(exp, regs[0], first, "lab-account-a")
    path = "/lab/checkin/claim"
    body = client.signed_payload(path, session)
    expected = "invalid_device_proof"
    if change == "device":
        body = client.signed_payload(path, session, device_id=regs[2].device_id)
        expected = "session_context_mismatch"
    elif change == "account":
        body = client.signed_payload(path, session, account_id="lab-account-b")
        expected = "session_context_mismatch"
    elif change == "unsigned_tamper":
        body["sandbox_device_id"] = regs[2].device_id
    elif change == "other_key":
        body["signature"] = store.sign(second, path, {k: v for k, v in body.items() if k != "signature"})
    elif change == "cross_path":
        body = client.signed_payload("/lab/checkin/status", session)
    elif change == "experiment":
        body["experiment_id"] = "lab-experiment-other"
        expected = "invalid_session"
    elif change == "stale":
        body["timestamp"] -= 61
        body["signature"] = store.sign(first, path, {k: v for k, v in body.items() if k != "signature"})
        expected = "stale_request"
    code, response = state.binding.protected(path, body)
    assert code == 403 and response["reason"] == expected
    assert not state.binding.ledger


def test_replayed_signed_claim_never_creates_second_ledger_entry(lab):
    client, state, store, regs, first, second, exp, clock = lab
    session = client.bind(exp, regs[0], first, "lab-account-a")
    body = client.signed_payload("/lab/checkin/claim", session)
    assert state.binding.protected("/lab/checkin/claim", body)[1]["granted"] is True
    assert state.binding.protected("/lab/checkin/claim", body)[1]["reason"] == "replayed_request"
    assert len(state.binding.ledger) == 1


def test_challenge_is_one_use_and_proof_is_required(lab):
    client, state, store, regs, first, second, exp, clock = lab
    _, response = state.binding.challenge(challenge_body(client, exp, regs[0], first))
    challenge = response["challenge"]
    body = {"experiment_id": exp, "app_id": client.config.app_id, "challenge_id": challenge["challenge_id"],
            "signature": store.sign(first, "/lab/bind", challenge)}
    assert state.binding.bind(body)[0] == 200
    assert state.binding.bind(body)[1]["reason"] == "challenge_not_found"
    assert len(state.binding.sessions) == 1
    _, response = state.binding.challenge(challenge_body(client, exp, regs[0], first))
    challenge = response["challenge"]
    bad = {**body, "challenge_id": challenge["challenge_id"], "signature": store.sign(second, "/lab/bind", challenge)}
    assert state.binding.bind(bad)[1]["reason"] == "invalid_device_proof"
    assert len(state.binding.sessions) == 1


def test_challenge_expiry_session_expiry_and_key_enrollment_race(lab):
    client, state, store, regs, first, second, exp, clock = lab
    body = challenge_body(client, exp, regs[0], first)
    _, response = state.binding.challenge(body)
    challenge = response["challenge"]
    clock[0] += 60
    assert state.binding.bind({"experiment_id": exp, "app_id": client.config.app_id,
        "challenge_id": challenge["challenge_id"], "signature": store.sign(first, "/lab/bind", challenge)})[1]["reason"] == "challenge_expired"
    _, one = state.binding.challenge(body)
    _, two = state.binding.challenge({**body, "key_id": second["key_id"], "public_key_pem": second["public_key_pem"]})
    for document, meta, expected in [(one, first, 200), (two, second, 403)]:
        challenge = document["challenge"]
        assert state.binding.bind({"experiment_id": exp, "app_id": client.config.app_id,
            "challenge_id": challenge["challenge_id"], "signature": store.sign(meta, "/lab/bind", challenge)})[0] == expected
    session = client.bind(exp, regs[0], first, "lab-account-a")
    clock[0] += 600
    body = client.signed_payload("/lab/checkin/claim", session)
    assert state.binding.protected("/lab/checkin/claim", body)[1]["reason"] == "invalid_session"


def test_server_day_is_beijing_and_new_day_has_a_new_quota(lab):
    client, state, store, regs, first, second, exp, clock = lab
    a = client.bind(exp, regs[0], first, "lab-account-a")
    assert client.claim(a)["business_day"] == "2026-11-20"
    clock[0] += 31
    assert client.claim(a)["business_day"] == "2026-11-21"
    assert len(state.binding.ledger) == 2
    assert {row["business_day"] for row in state.binding.ledger} == {"2026-11-20", "2026-11-21"}


def test_atomic_device_quota_with_two_accounts(lab):
    client, state, store, regs, first, second, exp, clock = lab
    a = client.bind(exp, regs[0], first, "lab-account-a")
    b = client.bind(exp, regs[1], second, "lab-account-b")
    path = "/lab/checkin/claim"
    bodies = [client.signed_payload(path, session) for session in (a, b)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda body: state.binding.protected(path, body), bodies))
    assert sum(response.get("granted") is True for code, response in replies) == 1
    assert sum(response.get("reason") == "device_daily_limit" for code, response in replies) == 1
    assert len(state.binding.ledger) == 1


def test_activated_registration_required(lab):
    client, state, store, regs, first, second, exp, clock = lab
    reg = client.register("lab-experiment-unactivated", DeviceFixture("fixture-a", attributes_for("fixture-a")))
    code, response = state.binding.challenge(challenge_body(client, "lab-experiment-unactivated", reg, first))
    assert code == 403 and response["reason"] == "activated_registration_required"


def test_claim_budget_prevents_seventh_attempt(lab):
    client, state, store, regs, first, second, exp, clock = lab
    session = client.bind(exp, regs[0], first, "lab-account-a")
    for _ in range(6):
        client.claim(session)
    before = client.requests_sent
    with pytest.raises(LabFailure, match="claim_budget_exhausted"):
        client.claim(session)
    assert client.requests_sent == before


def test_offline_binding_prepares_keys_without_network(cfg, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline binding created network/client")
    monkeypatch.setattr(httpx, "Client", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    report = run_binding(cfg)
    assert report["requests_sent"] == 0 and report["completion_status"] == "dry_run"
    assert report["local_account_binding"] == "not_run"
    assert len(list((cfg.output_directory / "profiles").glob("*.p256.secret"))) == 3


def test_real_http_binding_quota_and_report_redaction(cfg, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://192.0.2.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://192.0.2.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    with running_mock() as server:
        config = local_config(server.server_port, str(cfg.output_directory), scenario="binding_quota")
        report = run_binding(config, execute=True)
        assert report["completion_status"] == "passed"
        assert report["requests_sent"] == server.state.requests == report["planned_requests"] == 31
        assert report["claim_attempts"] == 6
        assert report["test_ledger"]["entries"] == 2
        assert report["test_ledger"]["h1_entries"] == report["test_ledger"]["h2_entries"] == 1
        assert [case["granted"] for case in report["cases"]] == [True, False, False, False, False, True]
        assert report["local_account_binding"] == report["local_device_quota"] == "passed"
        assert report["real_account_binding"] == report["online_checkin"] == report["provider_test"] == "not_run"
        text = Path(report["report_path"]).read_text(encoding="utf-8")
        for token, session in server.state.binding.sessions.items():
            assert token not in text and session["public_key_pem"] not in text
        assert "PRIVATE KEY" not in text and "signature" not in text and "session_token" not in text
        assert not server.socket.fileno() == -1
    assert server.socket.fileno() == -1


@pytest.mark.parametrize("budget", [1, 9, 16])
def test_binding_request_budget_stops_work(cfg, budget):
    with running_mock() as server:
        data = local_config(server.server_port, str(cfg.output_directory), scenario="binding_quota").as_dict()
        data["max_requests"] = budget
        report = run_binding(ExperimentConfig.from_dict(data), execute=True)
        assert report["completion_status"] == "budget_exhausted"
        assert report["requests_sent"] == server.state.requests == budget
        assert len(server.state.binding.ledger) <= 1


def test_legacy_capability_does_not_allow_binding(cfg):
    body = {key: value for key, value in CAPABILITIES.items() if key not in (
        "binding_protocol_version", "local_account_binding_enabled", "test_ledger_enabled", "account_authentication")}
    client = BindingClient(cfg, FixtureStore(cfg.output_directory), transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)))
    try:
        with pytest.raises(LabFailure, match="binding_capability_mismatch"):
            client.capabilities()
        assert client.ready is False
        assert client.requests_sent == 1
    finally:
        client.close()


def test_expanded_budget_and_binding_routes_are_local_scenario_only(cfg):
    assert cfg.max_requests == 32
    regular = local_config(8765, str(cfg.output_directory))
    data = regular.as_dict()
    data["max_requests"] = 32
    with pytest.raises(ValueError):
        ExperimentConfig.from_dict(data)
    with pytest.raises(ValueError):
        BindingClient(regular, FixtureStore(regular.output_directory))
    for change in [{"max_requests": 33}, {"base_url": "https://api.trae.cn"}, {"scenario": "production"}]:
        with pytest.raises(ValueError):
            ExperimentConfig.from_dict({**cfg.as_dict(), **change})


def test_empty_public_metadata_is_corruption_not_a_new_identity(cfg):
    store = FixtureStore(cfg.output_directory)
    path = store.directory / "lab-physical-h1-I1.installation.json"
    storage.atomic_json(path, {})
    with pytest.raises(ValueError):
        store.installation("lab-physical-h1", "I1")
    assert path.read_text().strip() == "{}"
    assert not list(store.directory.glob("*.secret"))


def test_claim_timeout_after_server_commit_is_not_retried(cfg):
    state = MockState()
    def handler(request):
        response = dispatch(state, request)
        if request.url.path == "/lab/checkin/claim":
            raise httpx.ReadTimeout("secret-session-must-not-be-reported", request=request)
        return response
    report = run_binding(cfg, execute=True, transport=httpx.MockTransport(handler))
    assert report["completion_status"] == "failed"
    assert report["requests_sent"] == 11 and report["claim_attempts"] == 1
    assert report["cases"][-1]["outcome_unknown"] is True
    assert len(state.binding.ledger) == 1
    assert "secret-session" not in json.dumps(report)


@pytest.mark.parametrize("phase", ["/lab/binding-challenge", "/lab/bind", "/lab/checkin/claim"])
def test_binding_redirects_never_follow_or_continue(cfg, phase):
    state = MockState()
    paths = []
    def handler(request):
        paths.append(request.url.path)
        if request.url.path == phase:
            return httpx.Response(307, headers={"Location": "https://not-a-local-mock.invalid"})
        return dispatch(state, request)
    report = run_binding(cfg, execute=True, transport=httpx.MockTransport(handler))
    assert report["completion_status"] == "failed"
    assert paths[-1] == phase
    assert report["cases"][-1]["label"] == "redirect_rejected"
    assert len(state.binding.ledger) == 0


@pytest.mark.parametrize("failure", ["challenge_context", "grant_type", "ledger_count"])
def test_malformed_binding_protocol_fails_without_success_claim(cfg, failure):
    state = MockState()
    def handler(request):
        response = dispatch(state, request)
        body = response.json()
        if failure == "challenge_context" and request.url.path == "/lab/binding-challenge":
            body["challenge"]["account_id"] = "lab-account-b"
        elif failure == "grant_type" and request.url.path == "/lab/checkin/claim" and body.get("granted") is True:
            body["granted"] = 1
        elif failure == "ledger_count" and request.url.path == "/lab/checkin/ledger":
            body["count"] = True
        return httpx.Response(response.status_code, json=body)
    report = run_binding(cfg, execute=True, transport=httpx.MockTransport(handler))
    assert report["completion_status"] == "failed"
    assert report["local_device_quota"] != "passed"
    assert report["cases"][-1]["state"] == "protocol_error"


def test_real_http_signature_failure_cannot_write_ledger(cfg):
    with running_mock() as server:
        config = local_config(server.server_port, str(cfg.output_directory), scenario="binding_quota")
        store = FixtureStore(cfg.output_directory)
        client = BindingClient(config, store)
        try:
            client.capabilities()
            exp = "lab-experiment-proof-" + uuid.uuid4().hex
            reg = client.register(exp, DeviceFixture("fixture-a", attributes_for("fixture-a")))
            client.activate(exp, reg)
            session = client.bind(exp, reg, store.installation("lab-physical-h1", "I1"), "lab-account-a")
            assert session.token not in repr(session)
            body = client.signed_payload("/lab/checkin/claim", session)
            body["signature"] = "invalid-signature"
            response = client.http.post(config.base_url + "/lab/checkin/claim", json=body)
            assert response.status_code == 403 and response.json()["reason"] == "invalid_device_proof"
            assert client.ledger(session)["count"] == 0
        finally:
            client.close()
