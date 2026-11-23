"""Allowlisted Trae diagnostics; never serialize exception messages or data."""
from __future__ import annotations

import re
import sqlite3

import httpx


def safe_error_fields(exc: BaseException) -> dict:
    """Return a fixed error category and vetted numeric protocol codes only."""
    chain = []
    current = exc
    while current is not None and len(chain) < 8 and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    fields = {'error_type': 'other', 'failure_category': 'unexpected'}
    if any(isinstance(e, (httpx.TimeoutException, TimeoutError)) for e in chain):
        fields.update(error_type='timeout', failure_category='network')
    elif any(isinstance(e, httpx.HTTPError) for e in chain):
        fields.update(error_type='http_error', failure_category='network')
    elif any(isinstance(e, sqlite3.Error) for e in chain):
        fields.update(error_type='sqlite_error', failure_category='storage')
    elif any(isinstance(e, OSError) for e in chain):
        fields.update(error_type='os_error', failure_category='storage')
    elif any(isinstance(e, ValueError) for e in chain):
        fields.update(error_type='value_error', failure_category='validation')
        # Match only fixed local errors; never emit the exception message.
        if any(type(e) is ValueError and str(e) == 'login token expired; sign in to Trae again' for e in chain):
            fields.update(error_type='token_expired', failure_category='authentication')
        elif any(type(e) is ValueError and str(e) in ('Trae account changed; restart the scheduler', 'account mismatch') for e in chain):
            fields.update(error_type='account_mismatch', failure_category='authentication')
        elif any(type(e) is ValueError and str(e) == 'device activation was not confirmed' for e in chain):
            fields.update(error_type='device_activation_unconfirmed', failure_category='device')
        elif any(type(e) is ValueError and str(e) == 'invalid device_pair.json; refusing to overwrite it' for e in chain):
            fields.update(error_type='device_pair_invalid', failure_category='storage')
        for item in chain:
            if type(item) is not ValueError:
                continue
            match = re.fullmatch(r'device (registration|activation) failed: HTTP ([1-5][0-9]{2})', str(item))
            if match:
                fields.update(error_type='device_' + match.group(1) + '_http_error',
                              failure_category='upstream', http_status=int(match.group(2)))
                break
            match = re.fullmatch(r'device (registration|activation) network error \((ReadTimeout|ConnectTimeout|WriteTimeout|PoolTimeout|ConnectError|ReadError|WriteError)\); not retried', str(item))
            if match:
                fields.update(error_type='timeout' if match.group(2).endswith('Timeout') else 'http_error',
                              failure_category='network')
                break
    # Only parse our own fixed-format CheckinError, not arbitrary server text.
    for item in chain:
        if type(item).__name__ != 'CheckinError' or type(item).__module__ != 'daily_checkin.trae':
            continue
        text = str(item)
        status = re.match(r'^(?:(?:status query|claim) failed: )?HTTP ([1-5][0-9]{2});', text)
        code = re.match(r'^(?:(?:status query|claim) failed: )?business or protocol error: code=(-?[0-9]{1,9})(?:;|$)', text)
        if status:
            fields.update(error_type='http_status', failure_category='upstream', http_status=int(status.group(1)))
        elif code:
            fields.update(error_type='business_error', failure_category='upstream', business_code=int(code.group(1)))
        elif fields['error_type'] == 'other':
            fields.update(error_type='checkin_error', failure_category='protocol')
    return fields
