"""Compatibility alias for Trae independent login."""
import sys
from pathlib import Path
from buddy_agent_auth.providers.trae import app_storage as _storage
from buddy_agent_auth.providers.trae import login as _module
_storage.configure_fallback(Path(__file__).resolve().parent.parent)
_module.configure_legacy_credentials(Path(__file__).resolve().parent / "trae2api.json")
if __name__ == "__main__":
    raise SystemExit(_module.main())
sys.modules[__name__] = _module
