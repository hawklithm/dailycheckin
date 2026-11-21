"""Compatibility alias for the Trae device store."""
import sys
from pathlib import Path
from buddy_agent_auth.providers.trae import app_storage as _module
_module.configure_fallback(Path(__file__).resolve().parent.parent)
sys.modules[__name__] = _module
