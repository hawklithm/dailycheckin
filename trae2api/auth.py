"""Compatibility access to Trae authentication with the original default path."""
from pathlib import Path
from buddy_agent_auth.providers.trae.auth import *  # legacy public symbols
from buddy_agent_auth.providers.trae.auth import TraeAuth as _SharedTraeAuth, _jwt_exp, _ms_to_iso, _parse_iso


class TraeAuth(_SharedTraeAuth):
    def __init__(self, storage_path=None, creds_file=None, client_id=DEFAULT_CLIENT_ID, http=None):
        if creds_file is None:
            creds_file = Path(__file__).parent / "trae2api.json"
        super().__init__(storage_path=storage_path, creds_file=creds_file, client_id=client_id, http=http)
