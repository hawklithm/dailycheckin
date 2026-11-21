"""Compatibility alias for the DailyCheckin Trae profile."""
import sys
from daily_checkin import trae_profile as _module
sys.modules[__name__] = _module
