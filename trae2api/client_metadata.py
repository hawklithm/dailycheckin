"""Compatibility alias for the Trae authentication provider."""
import sys
from buddy_agent_auth.providers.trae import client_metadata as _module
sys.modules[__name__] = _module
