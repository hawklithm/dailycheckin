"""Model catalog: prefer the live Trae cache, fall back to a static snapshot."""
from __future__ import annotations

import json
import os
from pathlib import Path

FALLBACK = Path(__file__).parent / "models_fallback.json"
TRAE_STATE = Path(os.environ.get("APPDATA", "")) / "Trae CN" / "User" / "globalStorage" / "state.vscdb"
CATALOG_KEY_SUFFIX = ":AI.agent.model.model_list_map"
KNOWN_USER_IDS = ("3481484447459108",)


class ModelCatalog:
    def __init__(self, categories: dict[str, list[dict]]) -> None:
        self.categories = categories

    @classmethod
    def load_default(cls) -> "ModelCatalog":
        cats = cls._from_trae_state()
        if not cats:
            cats = cls._from_fallback()
        return cls(cats)

    @classmethod
    def _from_trae_state(cls) -> dict[str, list[dict]]:
        if not TRAE_STATE.exists():
            return {}
        import sqlite3
        import shutil
        import tempfile
        try:
            with tempfile.NamedTemporaryFile(suffix=".vscdb", delete=False) as tmp:
                tmp_path = tmp.name
            shutil.copyfile(TRAE_STATE, tmp_path)  # fails if locked; state db readable usually
            con = sqlite3.connect(tmp_path)
            try:
                rows = con.execute("SELECT key, value FROM ItemTable").fetchall()
            finally:
                con.close()
            os.unlink(tmp_path)
        except Exception:
            return {}
        for key, value in rows:
            if isinstance(value, str) and key.endswith(CATALOG_KEY_SUFFIX):
                try:
                    data = json.loads(value)
                except json.JSONDecodeError:
                    continue
                cats = {}
                for cat, models in data.items():
                    if isinstance(models, list):
                        cats[cat] = [m for m in models if isinstance(m, dict) and m.get("name")]
                if cats:
                    return cats
        return {}

    @classmethod
    def _from_fallback(cls) -> dict[str, list[dict]]:
        if FALLBACK.exists():
            return json.loads(FALLBACK.read_text(encoding="utf-8"))
        return {}

    def model_names(self, category: str | None = None) -> list[str]:
        cat = category or "solo_agent"
        names: list[str] = []
        for c in (cat, "agent", "solo_coder"):
            for m in self.categories.get(c, []):
                n = m.get("name")
                if n and n not in names:
                    names.append(n)
        # dedupe keep order, include every category's names as a final resort
        if not names:
            for models in self.categories.values():
                for m in models:
                    n = m.get("name")
                    if n and n not in names:
                        names.append(n)
        return names

    def info(self, name: str) -> dict | None:
        for models in self.categories.values():
            for m in models:
                if m.get("name") == name:
                    return m
        return None
