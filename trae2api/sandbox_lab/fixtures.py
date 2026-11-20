"""Finite synthetic descriptions, with no real hardware or credential reads."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

from .storage import atomic_json, canonical, confined, read_json


FIXTURE_IDS = ("fixture-a", "fixture-a-display", "fixture-b", "fixture-invalid")


def attributes_for(fixture_id: str) -> dict:
    if fixture_id not in FIXTURE_IDS:
        raise ValueError("unknown fixed fixture ID")
    value = {"synthetic": True,
             "physical_key": "lab-physical-h2" if fixture_id == "fixture-b" else "lab-physical-h1",
             "model": "Synthetic Model B" if fixture_id == "fixture-b" else "Synthetic Model A",
             "display_name": "Synthetic H1 renamed" if fixture_id == "fixture-a-display" else "Synthetic device"}
    if fixture_id == "fixture-invalid":
        value["model"] = 17  # A deliberately invalid, persistent negative fixture.
    return value


def validate_attributes(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {"synthetic", "physical_key", "model", "display_name"}:
        raise ValueError("invalid synthetic attribute schema")
    if value["synthetic"] is not True:
        raise ValueError("attributes must be explicitly synthetic")
    if not isinstance(value["physical_key"], str) or not re.fullmatch(r"lab-physical-h[12]", value["physical_key"]):
        raise ValueError("invalid synthetic physical key")
    for key in ("model", "display_name"):
        if not isinstance(value[key], str) or not value[key].strip() or len(value[key]) > 100:
            raise ValueError("invalid synthetic description")


@dataclass(frozen=True)
class DeviceFixture:
    fixture_id: str
    attributes: dict

    @property
    def fixture_digest(self) -> str:
        return hashlib.sha256(canonical(self.attributes).encode()).hexdigest()

    def as_dict(self) -> dict:
        return {"schema_version": 1, "fixture_id": self.fixture_id,
                "case_description": self.fixture_id, "attributes": deepcopy(self.attributes),
                "fixture_digest": self.fixture_digest, "source_kind": "offline_fixture"}


class FixtureStore:
    def __init__(self, directory: Path):
        self.directory = confined(directory) / "profiles"

    def load_or_create(self, fixture_id: str) -> DeviceFixture:
        fixture = DeviceFixture(fixture_id, attributes_for(fixture_id))
        path = self.directory / (fixture_id + ".fixture.json")
        if not confined(path).exists():
            atomic_json(path, fixture.as_dict(), create_only=True)
        if canonical(read_json(path)) != canonical(fixture.as_dict()):
            raise ValueError("persisted fixture differs from its fixed definition")
        return fixture

    def installation(self, physical_key: str, installation_id: str) -> dict:
        from .keys import installation
        return installation(self.directory, physical_key, installation_id)

    def rebuild_installation(self, physical_key: str, installation_id: str) -> dict:
        from .keys import installation
        return installation(self.directory, physical_key, installation_id, rebuild=True)

    def sign(self, installation: dict, path: str, payload: dict) -> str:
        from .keys import sign
        return sign(self.directory, installation, path, payload)
