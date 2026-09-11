import logging

from django.contrib.sessions.backends.cached_db import SessionStore as CachedDBSessionStore
from django.contrib.sessions.backends.db import SessionStore as DBSessionStore
from django.utils.translation import gettext_lazy as _
from flags.state import flag_state

from ansible_base.lib.utils.settings import get_setting

DEFAULT_SESSION_TIMEOUT = 30 * 60
logger = logging.getLogger('ansible_base.lib.sessions.stores.cached_dynamic_timeout')


class SessionStore(CachedDBSessionStore):
    """
    Dynamic session store that can switch between cached and DB-only
    modes at runtime based on the FEATURE_GATEWAY_SIDECAR_CACHE_ENABLED feature flag.

    When sidecar cache is DISABLED (flag=False, default):
        - Sessions use cache + database (CachedDBSessionStore behavior)
        - Reads check cache first, fall back to DB

    When sidecar cache is ENABLED (flag=True):
        - Sessions use database only (DBSessionStore behavior)
        - Ensures logout/session invalidation is immediately consistent
          across all cluster nodes (no stale cached sessions)
    """

    cache_key_prefix = 'ansible_base.lib.sessions.stores.cached_dynamic_timeout'

    def get_session_cookie_age(self):
        timeout = get_setting('SESSION_COOKIE_AGE', DEFAULT_SESSION_TIMEOUT)
        if not isinstance(timeout, int):
            logger.error(
                _('SESSION_COOKIE_AGE was set to %(timeout)s which is an invalid int, defaulting to %(default)s')
                % {'timeout': timeout, 'default': DEFAULT_SESSION_TIMEOUT}
            )
            timeout = DEFAULT_SESSION_TIMEOUT
        return timeout

    def _dispatch(self, method_name, *args, **kwargs):
        """Route method calls to cached or DB-only parent based on feature flag."""
        # Sidecar cache enabled = DB only (no centralized cache)
        # Sidecar cache disabled = use centralized cache + DB
        use_cache = not flag_state('FEATURE_GATEWAY_SIDECAR_CACHE_ENABLED')
        parent = CachedDBSessionStore if use_cache else DBSessionStore
        return getattr(parent, method_name)(self, *args, **kwargs)

    def load(self):
        return self._dispatch('load')

    def exists(self, session_key):
        return self._dispatch('exists', session_key)

    def save(self, must_create=False):
        return self._dispatch('save', must_create=must_create)

    def delete(self, session_key=None):
        return self._dispatch('delete', session_key=session_key)
