"""Compatibility alias for the Trae authentication provider."""
import sys
from buddy_agent_auth.providers.trae import native_identity as _module
sys.modules[__name__] = _module
