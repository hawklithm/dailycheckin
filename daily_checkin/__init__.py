"""DailyCheckin: account-aware activity check-in for Trae CN."""
__version__ = "0.1.2"
from .trae import Account, CheckinError, checkin

__all__ = ["Account", "CheckinError", "checkin", "__version__"]
