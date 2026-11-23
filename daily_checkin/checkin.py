"""Public check-in API and command entry point."""
import sys
from .trae import Account, CheckinError, checkin, main as _trae_main

__all__ = ["Account", "CheckinError", "checkin", "main"]


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and (arguments[0] == 'login' or arguments[:2] == ['trae', 'login']):
        from pathlib import Path
        from buddy_agent_auth.providers.trae import login
        legacy = Path(__file__).resolve().parent.parent / 'trae2api' / 'trae2api.json'
        if legacy.is_file():
            login.configure_legacy_credentials(legacy)
        return login.main(arguments[2:] if arguments[0] == 'trae' else arguments[1:])
    if arguments[:2] == ['trae', 'schedule']:
        from .trae_scheduler import main as schedule_main
        return schedule_main(arguments[2:])
    if arguments and arguments[0] == 'trae':
        arguments = arguments[1:]
    if arguments and arguments[0] == 'workbuddy':
        from .workbuddy_cli import main as workbuddy_main
        return workbuddy_main(arguments[1:])
    return _trae_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
