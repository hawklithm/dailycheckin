"""DailyCheckin: account-aware activity check-in for Trae CN."""
__version__ = "0.1.1.dev1"
from .trae import Account, CheckinError, checkin

__all__ = ["Account", "CheckinError", "checkin", "__version__"]
