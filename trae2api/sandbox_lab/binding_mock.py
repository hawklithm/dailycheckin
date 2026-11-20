"""Local reference policy: signed sessions and atomic device/account day limits.

Accounts are fixed synthetic aliases, NOT OAuth-authenticated real users.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import time
import uuid

from .keys import key_id, verify


ACCOUNTS = ("lab-account-a", "lab-account-b")
BINDING_CAPABILITIES = {"binding_protocol_version": 1, "local_account_binding_enabled": True,
                        "test_ledger_enabled": True, "account_authentication": "fixed_synthetic_aliases"}
SIGNED_PATHS = ("/lab/checkin/status", "/lab/checkin/claim", "/lab/checkin/ledger")


class BindingState:
    def __init__(self, owner, *, clock=None):
        self.owner = owner
        self.clock = clock or time.time
        self.challenges: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}
        self.installations: dict[tuple, str] = {}
        self.ledger: list[dict] = []
        self.device_days: set[tuple] = set()
        self.account_days: set[tuple] = set()

    def day(self) -> str:
        return datetime.fromtimestamp(self.clock(), timezone(timedelta(hours=8))).date().isoformat()

    @staticmethod
    def rejected(reason: str, status: int = 403) -> tuple[int, dict]:
        return status, {"accepted": False, "reason": reason}

    def challenge(self, body: dict) -> tuple[int, dict]:
        from .mock_server import valid_context
        fields = {"experiment_id", "app_id", "account_id", "sandbox_device_id", "sandbox_install_id",
                  "machine_id", "key_id", "public_key_pem"}
        if set(body) != fields or not valid_context(body) or body.get("account_id") not in ACCOUNTS:
            return self.rejected("invalid_binding_input", 400)
        if not isinstance(body.get("machine_id"), str) or not re.fullmatch(r"lab-machine-[0-9a-f]{32}", body["machine_id"]):
            return self.rejected("invalid_binding_input", 400)
        try:
            if key_id(body["public_key_pem"]) != body["key_id"]:
                raise ValueError()
        except (ValueError, TypeError):
            return self.rejected("invalid_public_key", 400)
        with self.owner.lock:
            registration = next((value for key, value in self.owner.registrations.items()
                if key[:2] == (body["experiment_id"], body["app_id"])
                and value["sandbox_device_id"] == body["sandbox_device_id"]
                and value["sandbox_install_id"] == body["sandbox_install_id"]), None)
            activation = (body["experiment_id"], body["sandbox_device_id"], body["sandbox_install_id"])
            if registration is None or activation not in self.owner.activated:
                return self.rejected("activated_registration_required")
            installation = (body["experiment_id"], body["app_id"], body["sandbox_device_id"], body["machine_id"])
            if installation in self.installations and self.installations[installation] != body["key_id"]:
                return self.rejected("installation_key_conflict")
            if len(self.challenges) >= 1024:
                return self.rejected("mock_capacity", 429)
            challenge_id = "lab-challenge-" + uuid.uuid4().hex
            payload = {**body, "purpose": "local-account-binding", "challenge_id": challenge_id,
                       "nonce": "lab-challenge-nonce-" + uuid.uuid4().hex}
            self.challenges[challenge_id] = {"payload": payload, "expires": self.clock() + 60,
                "physical_id": registration["sandbox_physical_id"], "installation": installation}
            return 200, {"accepted": True, "challenge": dict(payload)}

    def bind(self, body: dict) -> tuple[int, dict]:
        from .mock_server import valid_context
        if (set(body) != {"experiment_id", "app_id", "challenge_id", "signature"} or not valid_context(body)
                or not isinstance(body["challenge_id"], str)):
            return self.rejected("invalid_binding_input", 400)
        with self.owner.lock:
            item = self.challenges.get(body["challenge_id"])
            if (not item or item["payload"]["experiment_id"] != body["experiment_id"]
                    or item["payload"]["app_id"] != body["app_id"]):
                return self.rejected("challenge_not_found")
            self.challenges.pop(body["challenge_id"])
            payload = item["payload"]
            if self.clock() >= item["expires"]:
                return self.rejected("challenge_expired")
            if not verify(payload["public_key_pem"], "/lab/bind", payload, body["signature"]):
                return self.rejected("invalid_device_proof")
            # Recheck after proof: another binding may have enrolled this
            # machine with a different key while its challenge was outstanding.
            enrolled = self.installations.get(item["installation"])
            if enrolled is not None and enrolled != payload["key_id"]:
                return self.rejected("installation_key_conflict")
            if len(self.sessions) >= 1024:
                return self.rejected("mock_capacity", 429)
            token = "lab-session-" + uuid.uuid4().hex
            self.installations[item["installation"]] = payload["key_id"]
            self.sessions[token] = {**payload, "physical_id": item["physical_id"],
                                    "expires": self.clock() + 600, "nonces": set()}
            return 200, {"accepted": True, "session_token": token, "account_id": payload["account_id"],
                         "sandbox_device_id": payload["sandbox_device_id"], "key_id": payload["key_id"]}

    def protected(self, path: str, body: dict) -> tuple[int, dict]:
        from .mock_server import valid_context
        fields = {"experiment_id", "app_id", "session_token", "account_id", "sandbox_device_id",
                  "timestamp", "nonce", "signature"}
        if (path not in SIGNED_PATHS or set(body) != fields or not valid_context(body)
                or not isinstance(body.get("session_token"), str) or not isinstance(body.get("nonce"), str)
                or not re.fullmatch(r"lab-request-[0-9a-f]{32}", body["nonce"])
                or type(body.get("timestamp")) is not int):
            return self.rejected("invalid_signed_input", 400)
        with self.owner.lock:
            session = self.sessions.get(body["session_token"])
            if (not session or self.clock() >= session["expires"]
                    or session["experiment_id"] != body["experiment_id"] or session["app_id"] != body["app_id"]):
                return self.rejected("invalid_session")
            if abs(self.clock() - body["timestamp"]) > 60:
                return self.rejected("stale_request")
            payload = {key: value for key, value in body.items() if key != "signature"}
            if not verify(session["public_key_pem"], path, payload, body["signature"]):
                return self.rejected("invalid_device_proof")
            if body["nonce"] in session["nonces"]:
                return self.rejected("replayed_request")
            session["nonces"].add(body["nonce"])
            if body["account_id"] != session["account_id"] or body["sandbox_device_id"] != session["sandbox_device_id"]:
                return self.rejected("session_context_mismatch")
            day = self.day()
            prefix = (session["experiment_id"], session["app_id"])
            device_key = (*prefix, session["physical_id"], day)
            account_key = (*prefix, session["account_id"], day)
            if path == "/lab/checkin/ledger":
                entries = [dict(row) for row in self.ledger if (row["experiment_id"], row["app_id"]) == prefix]
                return 200, {"accepted": True, "entries": entries, "count": len(entries), "business_day": day}
            checked, device_checked = account_key in self.account_days, device_key in self.device_days
            if path == "/lab/checkin/status":
                return 200, {"accepted": True, "enable": True, "checked_in": checked,
                             "did_checked_in": device_checked, "business_day": day}
            if checked or device_checked:
                return 200, {"accepted": False, "granted": False,
                             "reason": "account_daily_limit" if checked else "device_daily_limit", "business_day": day}
            # The check, both unique keys, and the test ledger append share one
            # server lock. Client-side gating is intentionally not relied upon.
            ledger_id = "lab-ledger-" + uuid.uuid4().hex
            self.device_days.add(device_key)
            self.account_days.add(account_key)
            self.ledger.append({"experiment_id": prefix[0], "app_id": prefix[1], "ledger_id": ledger_id,
                "account_id": session["account_id"], "physical_id": session["physical_id"], "business_day": day,
                "test_units": 1})
            return 200, {"accepted": True, "granted": True, "ledger_id": ledger_id, "business_day": day}
