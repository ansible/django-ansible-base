import pytest
from django.test import override_settings

from ansible_base.lib.sessions.stores.cached_dynamic_timeout import DEFAULT_SESSION_TIMEOUT, SessionStore


@pytest.mark.parametrize(
    "setting,expected",
    [
        (-1, -1),
        (0, 0),
        (12, 12),
        ('a', DEFAULT_SESSION_TIMEOUT),
        # We don't need to test if the setting is not passed because that would really test get_preference
    ],
)
def test_get_session_cookie_age(setting, expected):
    with override_settings(SESSION_COOKIE_AGE=setting):
        session_store = SessionStore()
        assert session_store.get_session_cookie_age() == expected
