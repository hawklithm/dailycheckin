"""This implementation deliberately supports loopback mock endpoints only."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
import json
import math
from pathlib import Path
from urllib.parse import urlsplit

from .fixtures import FIXTURE_IDS
from .storage import canonical, confined


@dataclass(frozen=True)
class ExperimentConfig:
    base_url: str
    output_directory: Path
    fixture_ids: tuple[str, ...]
    max_requests: int
    timeout_seconds: float
    allowed_cidrs: tuple[str, ...]
    app_id: str = "local-device-lab"
    scenario: str = "registration"

    @classmethod
    def from_dict(cls, data: dict) -> "ExperimentConfig":
        fields = {"schema_version", "environment", "app_id", "base_url", "allowed_cidrs", "max_requests",
                  "timeout_seconds", "fixture_ids", "output_directory"}
        if not isinstance(data, dict) or not fields.issubset(data) or set(data) - fields - {"scenario"}:
            raise ValueError("configuration has missing or unsupported fields")
        scenario = data.get("scenario", "registration")
        if scenario not in ("registration", "binding_quota"):
            raise ValueError("unknown local scenario")
        if type(data["schema_version"]) is not int or data["schema_version"] != 1 or data["environment"] != "sandbox":
            raise ValueError("configuration must use sandbox schema version 1")
        if data["app_id"] != "local-device-lab":
            raise ValueError("only the local-device-lab app is supported")
        url = data["base_url"]
        if not isinstance(url, str) or any(c.isspace() for c in url) or "?" in url or "#" in url:
            raise ValueError("invalid local mock URL")
        try:
            parts = urlsplit(url)
            valid = (parts.scheme == "http" and parts.hostname == "127.0.0.1" and parts.port is not None
                     and 1 <= parts.port <= 65535 and not parts.username and not parts.password
                     and parts.path in ("", "/") and parts.netloc == f"127.0.0.1:{parts.port}")
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("only http://127.0.0.1:<port> mock endpoints are supported")
        cidrs = data["allowed_cidrs"]
        if not isinstance(cidrs, list) or not 1 <= len(cidrs) <= 8:
            raise ValueError("explicit loopback CIDRs are required")
        try:
            networks = [ipaddress.ip_network(value, strict=True) for value in cidrs if isinstance(value, str)]
            loopback = ipaddress.ip_network("127.0.0.0/8")
            if (len(networks) != len(cidrs) or any(n.version != 4 or not n.subnet_of(loopback) for n in networks)
                    or not any(ipaddress.ip_address("127.0.0.1") in n for n in networks)):
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("CIDRs must be contained in loopback and include the endpoint") from None
        maximum = 32 if scenario == "binding_quota" else 8
        if type(data["max_requests"]) is not int or not 1 <= data["max_requests"] <= maximum:
            raise ValueError("request budget exceeds the local scenario limit")
        timeout = data["timeout_seconds"]
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise ValueError("timeout must be finite and between 0 and 30 seconds")
        ids = data["fixture_ids"]
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 3 or any(not isinstance(i, str) or i not in FIXTURE_IDS for i in ids)
                or len(ids) != len(set(ids)) or sum(i != "fixture-invalid" for i in ids) > (3 if scenario == "binding_quota" else 2)):
            raise ValueError("select at most two valid fixed fixtures and the negative fixture")
        if scenario == "binding_quota" and ids != ["fixture-a", "fixture-a-display", "fixture-b"]:
            raise ValueError("binding quota scenario requires the three fixed valid fixtures")
        if not isinstance(data["output_directory"], str) or not data["output_directory"]:
            raise ValueError("output_directory must be an isolated lab path")
        return cls(url.rstrip("/"), confined(data["output_directory"]), tuple(ids), data["max_requests"],
                   float(timeout), tuple(cidrs), scenario=scenario)

    @classmethod
    def load(cls, path: Path) -> "ExperimentConfig":
        if path.stat().st_size > 16 * 1024:
            raise ValueError("configuration exceeds size limit")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError):
            raise ValueError("invalid configuration JSON") from None
        return cls.from_dict(data)

    def as_dict(self) -> dict:
        return {"schema_version": 1, "environment": "sandbox", "app_id": self.app_id,
                "base_url": self.base_url, "allowed_cidrs": list(self.allowed_cidrs),
                "max_requests": self.max_requests, "timeout_seconds": self.timeout_seconds,
                "fixture_ids": list(self.fixture_ids), "output_directory": str(self.output_directory), "scenario": self.scenario}

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical(self.as_dict()).encode()).hexdigest()


def local_config(port: int, output_directory: str, *, scenario: str = "registration") -> ExperimentConfig:
    return ExperimentConfig.from_dict({"schema_version": 1, "environment": "sandbox", "app_id": "local-device-lab",
        "base_url": f"http://127.0.0.1:{port}", "allowed_cidrs": ["127.0.0.0/8"],
        "max_requests": 32 if scenario == "binding_quota" else 8,
        "timeout_seconds": 10, "fixture_ids": ["fixture-a", "fixture-a-display", "fixture-b"] if scenario == "binding_quota"
        else ["fixture-a", "fixture-b", "fixture-invalid"], "output_directory": output_directory, "scenario": scenario})
