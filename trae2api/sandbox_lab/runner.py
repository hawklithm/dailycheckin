"""Offline preparation or a finite local register/activate/replay experiment."""
from __future__ import annotations

from datetime import datetime, timezone
import uuid

from .client import LabClient, LabFailure
from .config import ExperimentConfig
from .fixtures import FixtureStore, validate_attributes
from .storage import atomic_json, confined


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def not_run() -> dict:
    return {"state": "not_run"}


def run(config: ExperimentConfig, *, execute: bool = False, transport=None) -> dict:
    config = ExperimentConfig.from_dict(config.as_dict())
    if config.scenario != "registration":
        raise ValueError("use the binding quota runner for this scenario")
    experiment_id = "lab-experiment-" + uuid.uuid4().hex
    report = {"schema_version": 1, "experiment_id": experiment_id, "started_at": now(),
              "source_kind": "local_mock" if execute else "offline_fixture", "config_digest": config.digest,
              "request_budget": config.max_requests, "requests_sent": 0, "fixture_results": [],
              "capability": not_run(), "account_binding": "not_run", "online_checkin": "not_run",
              "provider_test": "not_run", "completion_status": "dry_run" if not execute else "passed",
              "installation_model": "persistent_lab_p256_keys"}
    store = FixtureStore(config.output_directory)
    valid = []
    physical_keys = set()
    for fixture_id in config.fixture_ids:
        fixture = store.load_or_create(fixture_id)
        item = {"fixture_id": fixture_id, "fixture_digest": fixture.fixture_digest,
                "validation": not_run(), "registration": not_run(), "activation": not_run(), "replay": not_run()}
        report["fixture_results"].append(item)
        try:
            validate_attributes(fixture.attributes)
        except ValueError:
            item["validation"] = {"state": "rejected", "label": "invalid_synthetic_attributes",
                                  "expected_negative_case": fixture_id == "fixture-invalid"}
            continue
        item["validation"] = {"state": "accepted"}
        valid.append((fixture, item))
        physical_keys.add(fixture.attributes["physical_key"])
    report["installation_isolation"] = []
    for physical_key in sorted(physical_keys):
        first = store.installation(physical_key, "I1")
        second = store.installation(physical_key, "I2")
        if first["machine_id"] == second["machine_id"] or first["key_id"] == second["key_id"]:
            raise ValueError("synthetic installations must remain distinct")
        report["installation_isolation"].append({"physical_alias": physical_key, "same_physical_fixture": True,
            "distinct_machine_labels": first["machine_id"] != second["machine_id"],
            "distinct_p256_keys": first["key_id"] != second["key_id"]})
    report["planned_requests"] = 1 + 2 * len(valid) + (1 if valid else 0)
    if execute:
        client = LabClient(config, transport=transport)
        stage_target, stage_name = report, "capability"
        try:
            client.capabilities()
            report["capability"] = dict(client.last_observation)
            registered = []
            for index, (fixture, item) in enumerate(valid):
                stage_target, stage_name = item, "registration"
                registration = client.register(experiment_id, fixture)
                if any(registration.device_id == previous.device_id or registration.install_id == previous.install_id
                       for previous in registered):
                    client._fail("distinct_fixtures_share_registration")
                item["registration"] = dict(client.last_observation)
                if registered and registration.physical_id and registered[0].physical_id:
                    item["same_mock_physical_as_first"] = registration.physical_id == registered[0].physical_id
                registered.append(registration)
                stage_name = "activation"
                client.activate(experiment_id, registration)
                item["activation"] = dict(client.last_observation)
                if index == 0:
                    stage_name = "replay"
                    if client.register(experiment_id, fixture) != registration:
                        client._fail("replay_identity_changed")
                    item["replay"] = dict(client.last_observation)
        except LabFailure as exc:
            stage_target[stage_name] = exc.observation
            report["completion_status"] = "budget_exhausted" if exc.observation["state"] == "budget_exhausted" else "failed"
        finally:
            report["requests_sent"] = client.requests_sent
            client.close()
    report["finished_at"] = now()
    path = confined(config.output_directory / "reports" / (experiment_id + ".json"))
    report["report_path"] = str(path)
    atomic_json(path, report)
    return report
