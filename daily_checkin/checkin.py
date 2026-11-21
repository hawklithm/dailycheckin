"""Public check-in API and module entry point."""
from trae2api.checkin import Account, CheckinError, checkin, main

__all__ = ["Account", "CheckinError", "checkin", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
