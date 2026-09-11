import pytest
from unittest import mock

from django.contrib.sessions.models import Session
from django.core.cache import caches
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


FEATURE_FLAG_NAME = 'FEATURE_GATEWAY_SIDECAR_CACHE_ENABLED'


@pytest.fixture
def clean_cache():
    """Fixture to provide a clean cache for each test."""
    cache = caches['default']
    cache.clear()
    yield cache
    cache.clear()


@pytest.mark.django_db
class TestDynamicSessionStoreSwitching:
    """
    Tests for SessionStore dynamic switching between cached+DB and DB-only modes
    based on FEATURE_GATEWAY_SIDECAR_CACHE_ENABLED feature flag.

    When flag is DISABLED (default): sessions use cache + DB
    When flag is ENABLED: sessions use DB only (for sidecar cache deployments)
    """

    def test_db_only_mode_does_not_use_cache(self, clean_cache):
        """
        When FEATURE_GATEWAY_SIDECAR_CACHE_ENABLED=True (sidecar mode),
        sessions should be stored in DB only, not in cache.
        """
        with mock.patch(
            'ansible_base.lib.sessions.stores.cached_dynamic_timeout.flag_state',
            return_value=True  # Sidecar cache enabled = DB only
        ):
            # Create a session
            session = SessionStore()
            session['test_key'] = 'test_value'
            session.create()
            session_key = session.session_key

            # Verify session exists in database
            assert Session.objects.filter(session_key=session_key).exists(), "Session should exist in DB"

            # Verify session is NOT in cache
            cache_key = session.cache_key_prefix + session_key
            cached_data = clean_cache.get(cache_key)
            assert cached_data is None, "Session should NOT be in cache when sidecar cache is enabled (DB-only mode)"

            # Verify we can load the session (from DB)
            loaded_session = SessionStore(session_key=session_key)
            assert loaded_session.load().get('test_key') == 'test_value', "Should be able to load session from DB"

            # Clean up
            session.delete()

    def test_cached_mode_uses_cache_and_db(self, clean_cache):
        """
        When FEATURE_GATEWAY_SIDECAR_CACHE_ENABLED=False (default),
        sessions should be stored in both cache and DB.
        """
        with mock.patch(
            'ansible_base.lib.sessions.stores.cached_dynamic_timeout.flag_state',
            return_value=False  # Sidecar cache disabled = use cache + DB
        ):
            # Create a session
            session = SessionStore()
            session['test_key'] = 'cached_value'
            session.create()
            session_key = session.session_key

            # Verify session exists in database
            assert Session.objects.filter(session_key=session_key).exists(), "Session should exist in DB"

            # Verify session IS in cache
            cache_key = session.cache_key_prefix + session_key
            cached_data = clean_cache.get(cache_key)
            assert cached_data is not None, "Session should be in cache when sidecar cache is disabled"
            assert cached_data.get('test_key') == 'cached_value', "Cached data should match session data"

            # Clean up
            session.delete()

    def test_dynamic_switching_between_modes(self, clean_cache):
        """
        Verify that toggling FEATURE_GATEWAY_SIDECAR_CACHE_ENABLED on the fly
        changes session storage behavior without restart.
        """
        # Track current flag state
        flag_state_value = [True]  # Start with sidecar enabled (DB-only)

        def mock_flag_state(flag_name):
            if flag_name == FEATURE_FLAG_NAME:
                return flag_state_value[0]
            return False

        with mock.patch(
            'ansible_base.lib.sessions.stores.cached_dynamic_timeout.flag_state',
            side_effect=mock_flag_state
        ):
            # === Phase 1: Sidecar cache ENABLED (DB-only mode) ===
            flag_state_value[0] = True

            session1 = SessionStore()
            session1['phase'] = 'db_only'
            session1.create()
            session1_key = session1.session_key

            # Should be in DB but NOT in cache
            assert Session.objects.filter(session_key=session1_key).exists()
            cache_key1 = session1.cache_key_prefix + session1_key
            assert clean_cache.get(cache_key1) is None, "Session 1 should NOT be in cache (DB-only mode)"

            # === Phase 2: Sidecar cache DISABLED (cache + DB mode) ===
            flag_state_value[0] = False

            session2 = SessionStore()
            session2['phase'] = 'cached'
            session2.create()
            session2_key = session2.session_key

            # Should be in BOTH DB and cache
            assert Session.objects.filter(session_key=session2_key).exists()
            cache_key2 = session2.cache_key_prefix + session2_key
            cached_data2 = clean_cache.get(cache_key2)
            assert cached_data2 is not None, "Session 2 should be in cache (cached mode)"
            assert cached_data2.get('phase') == 'cached'

            # === Phase 3: Sidecar cache ENABLED again (DB-only) ===
            flag_state_value[0] = True

            session3 = SessionStore()
            session3['phase'] = 'db_only_again'
            session3.create()
            session3_key = session3.session_key

            # Should be in DB but NOT in cache
            assert Session.objects.filter(session_key=session3_key).exists()
            cache_key3 = session3.cache_key_prefix + session3_key
            assert clean_cache.get(cache_key3) is None, "Session 3 should NOT be in cache (DB-only mode again)"

            # Verify we can still load all sessions regardless of current mode
            # All sessions should be loadable from DB
            loaded1 = SessionStore(session_key=session1_key)
            assert loaded1.load().get('phase') == 'db_only'

            loaded2 = SessionStore(session_key=session2_key)
            assert loaded2.load().get('phase') == 'cached'

            loaded3 = SessionStore(session_key=session3_key)
            assert loaded3.load().get('phase') == 'db_only_again'

            # Clean up
            session1.delete()
            session2.delete()
            session3.delete()

    def test_exists_respects_mode(self, clean_cache):
        """Verify exists() checks the right backend based on mode."""
        flag_state_value = [False]  # Start with cached mode

        def mock_flag_state(flag_name):
            if flag_name == FEATURE_FLAG_NAME:
                return flag_state_value[0]
            return False

        with mock.patch(
            'ansible_base.lib.sessions.stores.cached_dynamic_timeout.flag_state',
            side_effect=mock_flag_state
        ):
            # Create session in cached mode (flag disabled)
            session = SessionStore()
            session['test'] = 'value'
            session.create()
            session_key = session.session_key

            # Verify exists works in cached mode (checks cache first)
            assert session.exists(session_key)

            # Switch to DB-only mode (flag enabled)
            flag_state_value[0] = True

            # Should still exist (checking DB)
            new_session = SessionStore()
            assert new_session.exists(session_key)

            # Clean up
            session.delete()

    def test_delete_clears_cache_in_cached_mode(self, clean_cache):
        """Verify delete() clears cache when in cached mode (flag disabled)."""
        with mock.patch(
            'ansible_base.lib.sessions.stores.cached_dynamic_timeout.flag_state',
            return_value=False  # Cached mode
        ):
            session = SessionStore()
            session['test'] = 'value'
            session.create()
            session_key = session.session_key
            cache_key = session.cache_key_prefix + session_key

            # Verify it's in cache
            assert clean_cache.get(cache_key) is not None

            # Delete the session
            session.delete()

            # Should be gone from both DB and cache
            assert not Session.objects.filter(session_key=session_key).exists()
            assert clean_cache.get(cache_key) is None

    def test_logout_consistency_scenario(self, clean_cache):
        """
        Simulate the scenario this feature flag is designed to solve:
        User logs out, session should be immediately invalid across all nodes.

        In sidecar cache mode (flag enabled), we don't cache sessions,
        so logout (session.delete()) immediately removes from DB and
        subsequent loads fail - even from a "different node" perspective.
        """
        with mock.patch(
            'ansible_base.lib.sessions.stores.cached_dynamic_timeout.flag_state',
            return_value=True  # Sidecar cache enabled (DB-only)
        ):
            # User logs in - session created
            session = SessionStore()
            session['user_id'] = 12345
            session.create()
            session_key = session.session_key

            # Verify session works
            loaded = SessionStore(session_key=session_key)
            assert loaded.load().get('user_id') == 12345

            # User clicks logout - session deleted
            session.delete()

            # Simulate request hitting "another node" - session should NOT work
            # (In cached mode without this flag, a stale cache could still have the session)
            another_node_session = SessionStore(session_key=session_key)
            loaded_data = another_node_session.load()
            assert loaded_data == {}, "Session should be empty after logout in DB-only mode"
            assert not Session.objects.filter(session_key=session_key).exists()
