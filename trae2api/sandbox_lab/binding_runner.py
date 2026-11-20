"""Fixed local account-switch/reinstall quota experiment, never production."""
from __future__ import annotations

from .binding_client import BindingClient
from .client import LabFailure
from .config import ExperimentConfig
from .fixtures import FixtureStore
from .runner import now
from .storage import atomic_json, confined
import uuid


def run_binding(config: ExperimentConfig, *, execute=False, transport=None) -> dict:
    config = ExperimentConfig.from_dict(config.as_dict())
    if config.scenario != "binding_quota":
        raise ValueError("binding quota scenario required")
    experiment = "lab-experiment-" + uuid.uuid4().hex
    report = {"schema_version": 1, "experiment_id": experiment, "started_at": now(),
        "source_kind": "local_mock" if execute else "offline_fixture", "scenario": "binding_quota",
        "config_digest": config.digest, "request_budget": config.max_requests, "planned_requests": 31,
        "claim_budget": 6, "requests_sent": 0, "claim_attempts": 0, "cases": [],
        "local_account_binding": "not_run", "local_device_quota": "not_run",
        "real_account_binding": "not_run", "online_checkin": "not_run", "provider_test": "not_run",
        "reward_kind": "in_memory_test_ledger_only", "account_authentication": "fixed_synthetic_aliases",
        "completion_status": "dry_run" if not execute else "passed"}
    store = FixtureStore(config.output_directory)
    fixtures = [store.load_or_create(name) for name in config.fixture_ids]
    first = store.installation("lab-physical-h1", "I1")
    before_rebuild = store.installation("lab-physical-h1", "I2")
    other = store.installation("lab-physical-h2", "I1")
    if first["machine_id"] == before_rebuild["machine_id"] or first["key_id"] == before_rebuild["key_id"]:
        raise ValueError("synthetic installations must remain distinct")
    report["installation_model"] = "persistent_lab_p256_keys"
    if execute:
        client = BindingClient(config, store, transport=transport)
        current = "capability"
        try:
            client.capabilities()
            report["capability"] = dict(client.last_observation)
            registrations = []
            for fixture in fixtures:
                current = "prepare-" + fixture.fixture_id
                registration = client.register(experiment, fixture)
                client.activate(experiment, registration)
                registrations.append(registration)
            d1, rebuilt_registration, d2 = registrations
            if (not d1.physical_id or d1.physical_id != rebuilt_registration.physical_id or d1.physical_id == d2.physical_id
                    or d1.device_id == rebuilt_registration.device_id):
                raise LabFailure("protocol_error", "mock_physical_grouping_mismatch")

            def require(condition: bool, label: str):
                if not condition:
                    raise LabFailure("protocol_error", label)

            current = "initial_account_claim"
            a = client.bind(experiment, d1, first, "lab-account-a")
            status = client.status(a)
            require(not status["checked_in"] and not status["did_checked_in"], "baseline_not_fresh")
            grant = client.claim(a)
            after = client.status(a)
            require(grant["granted"] and after["checked_in"] and after["did_checked_in"], "baseline_not_confirmed")
            day = grant["business_day"]
            report["cases"].append({"case": current, "state": "passed", "granted": True})

            current = "same_installation_switch_account"
            b = client.bind(experiment, d1, first, "lab-account-b")
            status = client.status(b)
            grant = client.claim(b)  # Deliberately reaches the mock's server gate.
            require(not status["checked_in"] and status["did_checked_in"] and not grant["granted"]
                    and grant["reason"] == "device_daily_limit" and grant["business_day"] == day, "account_switch_limit_failed")
            report["cases"].append({"case": current, "state": "passed", "granted": False, "reason": grant["reason"]})

            current = "rebuild_installation_switch_account"
            rebuilt = store.rebuild_installation("lab-physical-h1", "I2")
            changed = (rebuilt["key_id"] != before_rebuild["key_id"] and rebuilt["machine_id"] != before_rebuild["machine_id"])
            require(changed and rebuilt["physical_key"] == first["physical_key"], "installation_rebuild_invalid")
            rebuilt_session = client.bind(experiment, d1, rebuilt, "lab-account-b")
            status = client.status(rebuilt_session)
            grant = client.claim(rebuilt_session)
            require(not status["checked_in"] and status["did_checked_in"] and not grant["granted"]
                    and grant["reason"] == "device_daily_limit" and grant["business_day"] == day, "rebuild_limit_failed")
            report["cases"].append({"case": current, "state": "passed", "granted": False, "reason": grant["reason"],
                                    "new_machine_id": True, "new_p256_key": True, "same_mock_physical_device": True})

            current = "new_registration_same_physical_device"
            new_registration_session = client.bind(experiment, rebuilt_registration, rebuilt, "lab-account-b")
            status = client.status(new_registration_session)
            grant = client.claim(new_registration_session)
            require(not status["checked_in"] and status["did_checked_in"] and not grant["granted"]
                    and grant["reason"] == "device_daily_limit" and grant["business_day"] == day, "registration_limit_failed")
            report["cases"].append({"case": current, "state": "passed", "granted": False, "reason": grant["reason"],
                                    "new_registration": True, "same_mock_physical_device": True})

            current = "repeat_account_claim"
            grant = client.claim(a)
            require(not grant["granted"] and grant["reason"] == "account_daily_limit" and grant["business_day"] == day,
                    "repeat_account_limit_failed")
            report["cases"].append({"case": current, "state": "passed", "granted": False, "reason": grant["reason"]})

            current = "independent_device_control"
            independent = client.bind(experiment, d2, other, "lab-account-b")
            status = client.status(independent)
            grant = client.claim(independent)
            after = client.status(independent)
            require(not status["checked_in"] and not status["did_checked_in"] and grant["granted"]
                    and after["checked_in"] and grant["business_day"] == day, "independent_control_failed")
            report["cases"].append({"case": current, "state": "passed", "granted": True})

            current = "test_ledger_audit"
            ledger = client.ledger(a)
            rows = ledger["entries"]
            require(ledger["count"] == 2 and ledger["business_day"] == day
                    and all(row["business_day"] == day for row in rows)
                    and sum(row["physical_id"] == d1.physical_id for row in rows) == 1
                    and sum(row["physical_id"] == d2.physical_id for row in rows) == 1
                    and {row["account_id"] for row in rows} == {"lab-account-a", "lab-account-b"}, "test_ledger_quota_failed")
            report["test_ledger"] = {"entries": 2, "h1_entries": 1, "h2_entries": 1, "business_day": day}
            report["local_account_binding"] = report["local_device_quota"] = "passed"
        except LabFailure as exc:
            report["cases"].append({"case": current, **exc.observation})
            report["completion_status"] = "budget_exhausted" if exc.observation["state"] == "budget_exhausted" else "failed"
        except (OSError, ValueError, TypeError):
            report["cases"].append({"case": current, "state": "storage_error", "label": "local_identity_error"})
            report["completion_status"] = "failed"
        finally:
            report["requests_sent"] = client.requests_sent
            report["claim_attempts"] = client.claim_attempts
            client.close()
    report["finished_at"] = now()
    path = confined(config.output_directory / "reports" / (experiment + ".json"))
    report["report_path"] = str(path)
    atomic_json(path, report)
    return report
