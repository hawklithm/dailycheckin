"""WorkBuddy check-in HTTP adapters shared by host applications."""
from __future__ import annotations

from datetime import date
import math
import re
import time
from typing import Any, Callable

from fastapi import APIRouter

from .workbuddy import STATUS_PATH, CHECKIN_PATH, _SAFE_ERRORS
from .workbuddy_billing import forward_billing

_STATUSES = frozenset({'unknown', 'unchecked', 'checked', 'checking', 'signing', 'error'})
_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, TypeError, ValueError):
        return False


def safe_checkin(value: Any) -> dict[str, Any]:
    """Project the activity state to the existing non-sensitive public schema."""
    if not isinstance(value, dict):
        value = {}
    raw_date = value.get('date')
    checkin_date = time.strftime('%Y-%m-%d', time.gmtime(time.time() + 8 * 60 * 60))
    if isinstance(raw_date, str) and _DATE.fullmatch(raw_date):
        try:
            date.fromisoformat(raw_date)
            checkin_date = raw_date
        except ValueError:
            pass
    status = value.get('status')
    if not isinstance(status, str) or status not in _STATUSES:
        status = 'error'
    error = value.get('error')
    if not isinstance(error, str) or error not in _SAFE_ERRORS:
        error = '签到状态查询失败' if status == 'error' else None
    return {
        'date': checkin_date,
        'status': status,
        'checked': value.get('checked') if type(value.get('checked')) is bool else None,
        'last_checked_at': float(value['last_checked_at']) if _finite_number(value.get('last_checked_at')) else None,
        'last_checkin_at': float(value['last_checkin_at']) if _finite_number(value.get('last_checkin_at')) else None,
        'error': error,
        'next_checkin_at': float(value['next_checkin_at']) if _finite_number(value.get('next_checkin_at')) else None,
    }


def create_legacy_router(get_request_state: Callable[[], Any], diagnostic: Callable[..., Any]) -> APIRouter:
    """Expose historical raw billing endpoints with their original HTTP contract.

    These endpoints intentionally forward the upstream response; callers that
    need the checked-before-claim and persistent duplicate guard should use the
    account activity service instead.
    """
    router = APIRouter()

    @router.api_route('/v1/checkin-status', methods=['GET', 'POST'])
    async def checkin_status():
        return await forward_billing(get_request_state(), 'POST', STATUS_PATH, diagnostic)

    @router.post('/v1/checkin')
    async def checkin():
        return await forward_billing(get_request_state(), 'POST', CHECKIN_PATH, diagnostic)

    return router
