"""Compatibility alias for Trae authentication device support."""
import sys
from buddy_agent_auth.providers.trae import aha_native_semantics as _module
sys.modules[__name__] = _module
