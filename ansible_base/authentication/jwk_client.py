import hashlib
from typing import Any

from django.core.cache import cache
from jwt import PyJWK, PyJWKClient, PyJWKSet, get_unverified_header
from jwt.exceptions import PyJWKClientError, PyJWKError

from ansible_base.lib.utils.settings import get_setting

JWKS_REFRESH_COOLDOWN_SETTING = "external_oauth_jwks_refresh_cooldown_seconds"
DEFAULT_JWKS_REFRESH_COOLDOWN_SECONDS = 60
MAX_JWKS_REFRESH_COOLDOWN_SECONDS = 86400


class CachedJWKClient(PyJWKClient):
    """Adds a shared Django-cache layer to PyJWT's normal JWKS handling."""

    forced_refresh_cooldown = DEFAULT_JWKS_REFRESH_COOLDOWN_SECONDS

    def __init__(self, uri: str, **kwargs: Any) -> None:
        """Override PyJWT initialization to derive the shared-cache namespace from the provider URI."""
        super().__init__(uri, **kwargs)
        self.cache_timeout = kwargs.get("lifespan", 300)
        self._cache_namespace = hashlib.sha256(uri.encode()).hexdigest()
        self.forced_refresh_cooldown = self._configured_refresh_cooldown()

    @staticmethod
    def _configured_refresh_cooldown() -> int:
        """Return the bounded shared-cache cooldown for forced JWKS refreshes.

        Gateway supplies this through DAB's generic settings hook. Other DAB
        consumers safely use the default when they do not register the setting.
        A value of zero intentionally disables all refresh and fetch locking.
        """
        value = get_setting(JWKS_REFRESH_COOLDOWN_SETTING, DEFAULT_JWKS_REFRESH_COOLDOWN_SECONDS)
        if isinstance(value, int) and 0 <= value <= MAX_JWKS_REFRESH_COOLDOWN_SECONDS:
            return value
        return DEFAULT_JWKS_REFRESH_COOLDOWN_SECONDS

    @property
    def _jwk_set_cache_key(self) -> str:
        """Return the shared cache key for this provider's complete JWKS document."""
        return f"external_oauth_jwk_set:{self._cache_namespace}"

    @property
    def _refresh_lock_key(self) -> str:
        """Return the cooldown key that throttles forced key-set refreshes."""
        return f"external_oauth_jwks_refresh:{self._cache_namespace}"

    @property
    def _fetch_lock_key(self) -> str:
        """Return the short-lived lock used while one request fetches a JWKS document."""
        return f"external_oauth_jwks_fetch:{self._cache_namespace}"

    def _signing_key_cache_key(self, kid: str) -> str:
        """Return a cache key that safely scopes an individual signing key to this URI."""
        cache_identifier = hashlib.sha256(kid.encode()).hexdigest()
        return f"external_oauth_jwk:{self._cache_namespace}:{cache_identifier}"

    def get_jwk_set(self, refresh: bool = False) -> PyJWKSet:
        """Override PyJWT JWKS lookup to share provider keys and refresh coordination through Django's cache."""
        jwk_set = None if refresh else cache.get(self._jwk_set_cache_key)
        if jwk_set is None:
            use_locks = self.forced_refresh_cooldown > 0
            if refresh and use_locks and not cache.add(self._refresh_lock_key, True, timeout=self.forced_refresh_cooldown):
                raise PyJWKClientError("JWKS refresh is already in progress")
            if use_locks and not cache.add(self._fetch_lock_key, True, timeout=self.forced_refresh_cooldown):
                raise PyJWKClientError("JWKS fetch is already in progress")
            try:
                jwk_set = None if refresh else cache.get(self._jwk_set_cache_key)
                if jwk_set is None:
                    jwk_set = super().fetch_data()
                    cache.set(self._jwk_set_cache_key, jwk_set, timeout=self.cache_timeout)
            finally:
                if use_locks:
                    cache.delete(self._fetch_lock_key)

        if not isinstance(jwk_set, dict):
            raise PyJWKClientError("The JWKS endpoint did not return a JSON object")
        return PyJWKSet.from_dict(jwk_set)

    def get_signing_key_from_jwt(self, token: str | bytes) -> PyJWK:
        """Override PyJWT key lookup to cache a signing key by provider URI and JWT key ID across processes."""
        kid = get_unverified_header(token).get("kid")
        if not kid:
            raise PyJWKClientError("JWT header is missing kid")

        cache_key = self._signing_key_cache_key(kid)
        cached_jwk = cache.get(cache_key)
        if cached_jwk is not None:
            try:
                return PyJWK.from_dict(cached_jwk)
            except (AttributeError, PyJWKError):
                cache.delete(cache_key)

        signing_key = super().get_signing_key_from_jwt(token)
        # PyJWT exposes no public JWK serializer; cache its original JSON-safe
        # JWK data rather than the non-serializable cryptography key object.
        cache.set(cache_key, signing_key._jwk_data, timeout=self.cache_timeout)
        return signing_key

    def refresh_signing_key_from_jwt(self, token: str) -> PyJWK:
        """Refresh a JWT signing key once the provider's cooldown permits it.

        Check the cooldown before evicting the current signing key so repeated
        forged signatures do not churn a still-valid shared cache entry.
        """
        kid = get_unverified_header(token).get("kid")
        if not kid:
            raise PyJWKClientError("JWT header is missing kid")

        if self.forced_refresh_cooldown > 0 and cache.get(self._refresh_lock_key) is not None:
            raise PyJWKClientError("JWKS refresh is already in progress")

        cache.delete(self._signing_key_cache_key(kid))
        signing_keys = self.get_signing_keys(refresh=True)
        signing_key = self.match_kid(signing_keys, kid)
        if not signing_key:
            raise PyJWKClientError(f"Unable to find a signing key that matches: {kid}")
        cache.set(self._signing_key_cache_key(kid), signing_key._jwk_data, timeout=self.cache_timeout)
        return signing_key
