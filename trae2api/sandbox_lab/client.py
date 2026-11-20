"""Budgeted loopback client with strict protocol checks and no retries."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time

import httpx

from .config import ExperimentConfig
from .fixtures import DeviceFixture, attributes_for, validate_attributes


class LabFailure(Exception):
    def __init__(self, state: str, label: str, *, http_status=None, elapsed_ms=0, outcome_unknown=False):
        super().__init__(label)
        self.observation = {"state": state, "label": label, "http_status": http_status,
                            "elapsed_ms": elapsed_ms, "outcome_unknown": outcome_unknown}


@dataclass(frozen=True)
class Registration:
    device_id: str
    install_id: str
    physical_id: str | None


class LabClient:
    def __init__(self, config: ExperimentConfig, *, transport: httpx.BaseTransport | None = None):
        self.config = ExperimentConfig.from_dict(config.as_dict())
        self.requests_sent = 0
        self.ready = False
        self.last_observation: dict = {}
        self.last_method: str | None = None
        self.registrations: set[tuple] = set()
        self.http = httpx.Client(timeout=self.config.timeout_seconds, trust_env=False,
                                 follow_redirects=False, transport=transport)

    def close(self) -> None:
        self.http.close()

    def _exchange(self, method: str, path: str, payload: dict | None = None) -> dict:
        operations = (("GET", "/lab/capabilities"), ("POST", "/lab/register"), ("POST", "/lab/activate"))
        binding_paths = ("/lab/binding-challenge", "/lab/bind", "/lab/checkin/status", "/lab/checkin/claim", "/lab/checkin/ledger")
        if (method, path) not in operations and not (self.config.scenario == "binding_quota" and method == "POST" and path in binding_paths):
            raise LabFailure("protocol_error", "unsupported_operation")
        if self.requests_sent >= self.config.max_requests:
            raise LabFailure("budget_exhausted", "request_budget_exhausted")
        self.requests_sent += 1  # Count attempts, including timeouts and errors.
        self.last_method = method
        start = time.monotonic()
        status = None
        try:
            with self.http.stream(method, self.config.base_url + path, json=payload) as response:
                status = response.status_code
                if 300 <= status < 400:
                    raise LabFailure("protocol_error", "redirect_rejected", http_status=status)
                if status != 200:
                    raise LabFailure("rejected" if 400 <= status < 500 else "protocol_error",
                                     "http_status", http_status=status, outcome_unknown=method == "POST")
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 64 * 1024:
                        raise LabFailure("protocol_error", "response_too_large", http_status=status,
                                         outcome_unknown=method == "POST")
                try:
                    body = json.loads(raw)
                except (ValueError, UnicodeError):
                    raise LabFailure("protocol_error", "invalid_json", http_status=status,
                                     outcome_unknown=method == "POST") from None
                if not isinstance(body, dict):
                    raise LabFailure("protocol_error", "response_not_object", http_status=status,
                                     outcome_unknown=method == "POST")
        except httpx.HTTPError:
            raise LabFailure("network_error", "network_outcome_unknown", http_status=status,
                             elapsed_ms=round((time.monotonic() - start) * 1000),
                             outcome_unknown=method == "POST") from None
        except LabFailure as exc:
            exc.observation["elapsed_ms"] = round((time.monotonic() - start) * 1000)
            raise
        self.last_observation = {"state": "accepted", "label": "protocol_accepted", "http_status": status,
                                 "elapsed_ms": round((time.monotonic() - start) * 1000), "outcome_unknown": False}
        return body

    def _fail(self, label: str, *, state="protocol_error") -> None:
        raise LabFailure(state, label, http_status=self.last_observation.get("http_status"),
                         elapsed_ms=self.last_observation.get("elapsed_ms", 0),
                         outcome_unknown=state == "protocol_error" and self.last_method == "POST")

    def capabilities(self) -> None:
        body = self._exchange("GET", "/lab/capabilities")
        if (body.get("service") != "device-registration-lab" or body.get("environment") != "sandbox"
                or body.get("rewards_enabled") is not False
                or type(body.get("protocol_version")) is not int or body["protocol_version"] != 1
                or type(body.get("supported_fixture_schema")) is not int or body["supported_fixture_schema"] != 1):
            self._fail("capability_mismatch")
        self.ready = True
        self.capability_body = body

    def _accepted(self, body: dict) -> None:
        if body.get("accepted") is False:
            self._fail("business_rejected", state="rejected")
        if body.get("accepted") is not True:
            self._fail("invalid_accepted_type")

    def register(self, experiment_id: str, fixture: DeviceFixture) -> Registration:
        if not self.ready:
            raise LabFailure("protocol_error", "capability_required")
        validate_attributes(fixture.attributes)
        if fixture.attributes != attributes_for(fixture.fixture_id):
            raise ValueError("only fixed synthetic fixtures may be sent")
        body = self._exchange("POST", "/lab/register", {"experiment_id": experiment_id,
            "fixture_id": fixture.fixture_id, "app_id": self.config.app_id, "attributes": fixture.attributes})
        self._accepted(body)
        values = [body.get("sandbox_device_id"), body.get("sandbox_install_id")]
        physical = body.get("sandbox_physical_id")
        if any(not isinstance(value, str) or not re.fullmatch(r"lab-[a-z0-9-]{1,100}", value) for value in values):
            self._fail("invalid_sandbox_ids")
        if physical is not None and (not isinstance(physical, str) or not re.fullmatch(r"lab-[a-z0-9-]{1,100}", physical)):
            self._fail("invalid_physical_id")
        registration = Registration(*values, physical)
        self.registrations.add((experiment_id, registration.device_id, registration.install_id))
        return registration

    def activate(self, experiment_id: str, registration: Registration) -> None:
        if not self.ready or (experiment_id, registration.device_id, registration.install_id) not in self.registrations:
            raise LabFailure("protocol_error", "registration_not_in_this_experiment")
        body = self._exchange("POST", "/lab/activate", {"experiment_id": experiment_id, "app_id": self.config.app_id,
            "sandbox_device_id": registration.device_id, "sandbox_install_id": registration.install_id})
        self._accepted(body)
        if body.get("activated") is not True:
            self._fail("activation_not_confirmed")
