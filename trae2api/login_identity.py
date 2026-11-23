"""Compatibility alias for Trae authentication device support."""
import sys
from buddy_agent_auth.providers.trae import login_identity as _module
sys.modules[__name__] = _module
