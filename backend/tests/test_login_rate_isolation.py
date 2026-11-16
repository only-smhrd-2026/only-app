"""테스트 간 카운터는 독립이며 한 테스트 안에서는 기존 로그인 제한을 유지한다."""

import pytest

from app.config import LOGIN_RATE_PER_MIN
from app.security import login_allowed


@pytest.mark.parametrize("run", [1, 2])
def test_each_test_has_fresh_counter_and_still_enforces_limit(run):
    assert all(login_allowed("testclient") for _ in range(LOGIN_RATE_PER_MIN))
    assert login_allowed("testclient") is False
