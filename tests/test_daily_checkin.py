import subprocess
import sys

import pytest

import daily_checkin
from daily_checkin import checkin as public_checkin
from trae2api import checkin as implementation


def test_public_api_reuses_existing_implementation():
    assert daily_checkin.Account is implementation.Account
    assert daily_checkin.CheckinError is implementation.CheckinError
    assert public_checkin is implementation.checkin


@pytest.mark.parametrize('module', ['daily_checkin', 'daily_checkin.checkin'])
def test_new_cli_runs_dry_without_credentials_or_network(module):
    result = subprocess.run([sys.executable, '-m', module, '--native'],
                            capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0
    assert 'Dry run' in result.stdout
