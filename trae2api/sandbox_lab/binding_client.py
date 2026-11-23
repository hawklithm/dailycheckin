"""Signed mock sessions, usable exclusively in the loopback quota scenario."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import re
import time
import uuid

from .binding_mock import ACCOUNTS, SIGNED_PATHS
from .client import LabClient, LabFailure, Registration
from .fixtures import FixtureStore


@dataclass(frozen=True)
class MockSession:
    experiment_id: str
    account_id: str
    device_id: str
    token: str = field(repr=False)
    installation: dict = field(repr=False)


class BindingClient(LabClient):
    def __init__(self, config, store: FixtureStore, *, transport=None, clock=None):
        if config.scenario != "binding_quota":
            raise ValueError("signed mock sessions require the local quota scenario")
        super().__init__(config, transport=transport)
        self.store = store
        self.clock = clock or time.time
        self.claim_attempts = 0

    def capabilities(self) -> None:
        super().capabilities()
        body = self.capability_body
        if (type(body.get("binding_protocol_version")) is not int or body["binding_protocol_version"] != 1
                or body.get("local_account_binding_enabled") is not True or body.get("test_ledger_enabled") is not True
                or body.get("account_authentication") != "fixed_synthetic_aliases"):
            self.ready = False
            self._fail("binding_capability_mismatch")

    def bind(self, experiment_id: str, registration: Registration, installation: dict, account_id: str) -> MockSession:
        if not self.ready or (experiment_id, registration.device_id, registration.install_id) not in self.registrations:
            raise LabFailure("protocol_error", "registration_not_in_this_experiment")
        if account_id not in ACCOUNTS:
            raise ValueError("only fixed synthetic account aliases are supported")
        request = {"experiment_id": experiment_id, "app_id": self.config.app_id, "account_id": account_id,
            "sandbox_device_id": registration.device_id, "sandbox_install_id": registration.install_id,
            "machine_id": installation["machine_id"], "key_id": installation["key_id"],
            "public_key_pem": installation["public_key_pem"]}
        response = self._exchange("POST", "/lab/binding-challenge", request)
        self._accepted(response)
        challenge = response.get("challenge")
        if (not isinstance(challenge, dict) or set(challenge) != set(request) | {"purpose", "challenge_id", "nonce"}
                or any(challenge.get(key) != value for key, value in request.items())
                or challenge.get("purpose") != "local-account-binding"
                or not _id(challenge.get("challenge_id"), "lab-challenge-")
                or not _id(challenge.get("nonce"), "lab-challenge-nonce-")):
            self._fail("invalid_binding_challenge")
        signature = self.store.sign(installation, "/lab/bind", challenge)
        body = self._exchange("POST", "/lab/bind", {"experiment_id": experiment_id, "app_id": self.config.app_id,
            "challenge_id": challenge["challenge_id"], "signature": signature})
        self._accepted(body)
        if (not _id(body.get("session_token"), "lab-session-") or body.get("account_id") != account_id
                or body.get("sandbox_device_id") != registration.device_id or body.get("key_id") != installation["key_id"]):
            self._fail("invalid_bound_session")
        return MockSession(experiment_id, account_id, registration.device_id, body["session_token"], dict(installation))

    def signed_payload(self, path: str, session: MockSession, *, device_id=None, account_id=None) -> dict:
        if path not in SIGNED_PATHS:
            raise ValueError("unsupported local signed operation")
        payload = {"experiment_id": session.experiment_id, "app_id": self.config.app_id, "session_token": session.token,
            "account_id": session.account_id if account_id is None else account_id,
            "sandbox_device_id": session.device_id if device_id is None else device_id,
            "timestamp": int(self.clock()), "nonce": "lab-request-" + uuid.uuid4().hex}
        return {**payload, "signature": self.store.sign(session.installation, path, payload)}

    def _signed(self, path: str, session: MockSession) -> dict:
        if not self.ready:
            raise LabFailure("protocol_error", "capability_required")
        return self._exchange("POST", path, self.signed_payload(path, session))

    def status(self, session: MockSession) -> dict:
        body = self._signed("/lab/checkin/status", session)
        self._accepted(body)
        if any(type(body.get(key)) is not bool for key in ("enable", "checked_in", "did_checked_in")) or not _day(body.get("business_day")):
            self._fail("invalid_checkin_status")
        return {key: body[key] for key in ("enable", "checked_in", "did_checked_in", "business_day")}

    def claim(self, session: MockSession) -> dict:
        if self.claim_attempts >= 6:
            raise LabFailure("budget_exhausted", "claim_budget_exhausted")
        before = self.requests_sent
        try:
            body = self._signed("/lab/checkin/claim", session)
        finally:
            self.claim_attempts += int(self.requests_sent > before)
        if not _day(body.get("business_day")):
            self._fail("invalid_claim_day")
        if body.get("accepted") is False and body.get("granted") is False and body.get("reason") in ("account_daily_limit", "device_daily_limit"):
            return {"granted": False, "reason": body["reason"], "business_day": body["business_day"]}
        self._accepted(body)
        if body.get("granted") is not True or not _id(body.get("ledger_id"), "lab-ledger-"):
            self._fail("invalid_test_grant")
        return {"granted": True, "business_day": body["business_day"]}

    def ledger(self, session: MockSession) -> dict:
        body = self._signed("/lab/checkin/ledger", session)
        self._accepted(body)
        rows = body.get("entries")
        if (not isinstance(rows, list) or len(rows) > 32 or type(body.get("count")) is not int
                or body["count"] != len(rows) or not _day(body.get("business_day"))):
            self._fail("invalid_test_ledger")
        ids = set()
        for row in rows:
            if (not isinstance(row, dict) or set(row) != {"experiment_id", "app_id", "ledger_id", "account_id", "physical_id", "business_day", "test_units"}
                    or row.get("experiment_id") != session.experiment_id or row.get("app_id") != self.config.app_id
                    or row.get("account_id") not in ACCOUNTS or not _id(row.get("ledger_id"), "lab-ledger-")
                    or not _id(row.get("physical_id"), "lab-physical-") or not _day(row.get("business_day"))
                    or type(row.get("test_units")) is not int or row["test_units"] != 1 or row["ledger_id"] in ids):
                self._fail("invalid_test_ledger_row")
            ids.add(row["ledger_id"])
        return {"count": len(rows), "entries": rows, "business_day": body["business_day"]}


def _id(value, prefix: str) -> bool:
    return isinstance(value, str) and re.fullmatch(re.escape(prefix) + "[0-9a-f]{32}", value) is not None


def _day(value) -> bool:
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False
