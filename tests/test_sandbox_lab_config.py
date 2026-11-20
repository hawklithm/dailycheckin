import json

import pytest

from trae2api.sandbox_lab import storage
from trae2api.sandbox_lab.config import ExperimentConfig, local_config
from trae2api.sandbox_lab.fixtures import FixtureStore, validate_attributes


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "OUTPUT_ROOT", tmp_path / "lab")
    return local_config(8765, str(tmp_path / "lab" / "experiment"))


@pytest.mark.parametrize("url", [
    "https://api.trae.cn", "http://localhost:8765", "http://127.1:8765", "http://2130706433:8765",
    "http://10.0.0.1:8765", "http://169.254.169.254:80", "http://8.8.8.8:8765",
    "http://0.0.0.0:8765", "http://[::1]:8765", "http://127.0.0.1", "https://127.0.0.1:8765",
    "http://127.0.0.1:0", "http://127.0.0.1:65536", "http://127.0.0.1:abc", "http://127.0.0.1:08765",
    "http://user:password@127.0.0.1:8765", "http://127.0.0.1:8765/lab/register",
    "http://127.0.0.1:8765?", "http://127.0.0.1:8765#", "http://127.0.0.1:8765\n",
])
def test_endpoint_rejections(cfg, url):
    data = cfg.as_dict()
    data["base_url"] = url
    with pytest.raises(ValueError):
        ExperimentConfig.from_dict(data)


@pytest.mark.parametrize("key,value", [
    ("schema_version", True), ("environment", "production"), ("app_id", "787976"),
    ("allowed_cidrs", ["0.0.0.0/0"]), ("allowed_cidrs", ["10.0.0.0/8"]),
    ("allowed_cidrs", ["127.0.0.2/32"]), ("allowed_cidrs", ["127.0.0.1/8"]),
    ("allowed_cidrs", [False]), ("allowed_cidrs", []), ("allowed_cidrs", ["::/0"]),
    ("max_requests", True), ("max_requests", 9), ("max_requests", 0),
    ("timeout_seconds", True), ("timeout_seconds", float("nan")), ("timeout_seconds", float("inf")),
    ("timeout_seconds", 0), ("timeout_seconds", 31),
    ("fixture_ids", ["../../account"]), ("fixture_ids", ["fixture-a", "fixture-a"]),
    ("fixture_ids", ["fixture-a", "fixture-a-display", "fixture-b"]), ("fixture_ids", [None]),
])
def test_strict_schema(cfg, key, value):
    data = cfg.as_dict()
    data[key] = value
    with pytest.raises(ValueError):
        ExperimentConfig.from_dict(data)


def test_unsupported_credential_or_proxy_fields_rejected(cfg):
    for key in ("token", "credentials", "proxy", "headers"):
        data = cfg.as_dict()
        data[key] = "must-not-be-used"
        with pytest.raises(ValueError):
            ExperimentConfig.from_dict(data)


def test_paths_confined_and_traversal_rejected(cfg, tmp_path):
    for path in (str(tmp_path / "outside"), str(storage.OUTPUT_ROOT / ".." / "escape"), "trae2api/trae2api.json"):
        data = cfg.as_dict()
        data["output_directory"] = path
        with pytest.raises(ValueError):
            ExperimentConfig.from_dict(data)


def test_profiles_persist_without_overwriting_corruption(cfg):
    store = FixtureStore(cfg.output_directory)
    fixture = store.load_or_create("fixture-a")
    assert store.load_or_create("fixture-a") == fixture
    path = cfg.output_directory / "profiles/fixture-a.fixture.json"
    document = json.loads(path.read_text())
    document["attributes"]["model"] = "corrupted"
    path.write_text(json.dumps(document))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="fixed definition"):
        store.load_or_create("fixture-a")
    assert path.read_bytes() == before


def test_synthetic_installs_are_stable_and_separate_from_physical_fixture(cfg):
    store = FixtureStore(cfg.output_directory)
    first, second = store.installation("lab-physical-h1", "I1"), store.installation("lab-physical-h1", "I2")
    assert store.installation("lab-physical-h1", "I1") == first
    assert first["machine_id"] != second["machine_id"]
    assert first["key_label"] != second["key_label"]
    assert first["physical_key"] == second["physical_key"]
    assert "private" not in json.dumps(first).lower()
    assert first["key_kind"] == "ecdsa_p256"
    store.load_or_create("fixture-a")
    renamed = store.load_or_create("fixture-a-display")
    other = store.load_or_create("fixture-b")
    assert renamed.attributes["physical_key"] == first["physical_key"]
    assert other.attributes["physical_key"] != first["physical_key"]
    with pytest.raises(ValueError):
        validate_attributes(store.load_or_create("fixture-invalid").attributes)


def test_invalid_installation_not_silently_regenerated(cfg):
    store = FixtureStore(cfg.output_directory)
    store.installation("lab-physical-h1", "I1")
    path = cfg.output_directory / "profiles/lab-physical-h1-I1.installation.json"
    path.write_text('{"schema_version":1}')
    before = path.read_bytes()
    with pytest.raises(ValueError):
        store.installation("lab-physical-h1", "I1")
    assert path.read_bytes() == before


def test_symlink_output_escape_rejected(cfg, tmp_path):
    storage.OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = storage.OUTPUT_ROOT / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks not permitted on this host")
    with pytest.raises(ValueError):
        storage.confined(link / "file.json")


def test_symlink_of_the_output_root_itself_is_rejected(cfg, tmp_path):
    outside = tmp_path / "outside-root"
    outside.mkdir()
    try:
        storage.OUTPUT_ROOT.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks not permitted on this host")
    with pytest.raises(ValueError):
        storage.confined(storage.OUTPUT_ROOT / "file.json")


def test_atomic_report_failure_keeps_previous_file(cfg, monkeypatch):
    path = cfg.output_directory / "reports/existing.json"
    storage.atomic_json(path, {"old": True})
    before = path.read_bytes()
    def fail_replace(*args):
        raise OSError("simulated write failure")
    monkeypatch.setattr(storage.os, "replace", fail_replace)
    with pytest.raises(OSError):
        storage.atomic_json(path, {"new": True})
    assert path.read_bytes() == before
    assert not list(path.parent.glob(".lab-*.tmp"))
