import hashlib
import random
import time
from typing import Any
from uuid import uuid4

from django.core.cache import cache
from jwt import PyJWK, PyJWKClient, PyJWKSet, get_unverified_header
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError, PyJWKError, PyJWKSetError

from ansible_base.lib.utils.settings import get_setting

JWKS_REFRESH_COOLDOWN_SETTING = "jwks_refresh_cooldown_seconds"
DEFAULT_JWKS_REFRESH_COOLDOWN_SECONDS = 60
MAX_JWKS_REFRESH_COOLDOWN_SECONDS = 86400
INITIAL_JWKS_FETCH_RETRY_SECONDS = 0.02
MAX_JWKS_FETCH_RETRY_SECONDS = 0.25


class JWKSFetchTimeoutError(PyJWKClientConnectionError):
    """A peer did not finish a coordinated JWKS fetch within the wait budget."""


class _JWKSRetry(Exception):
    """Internal signal that a JWKS coordination marker is currently held."""


class CachedJWKClient(PyJWKClient):
    """Adds a shared Django-cache layer to PyJWT's normal JWKS handling."""

    forced_refresh_cooldown = DEFAULT_JWKS_REFRESH_COOLDOWN_SECONDS

    def __init__(self, uri: str, **kwargs: Any) -> None:
        """Initialize a client whose JWKS cache is owned exclusively by Django's shared cache."""
        # PyJWT's per-instance cache writes the raw response before DAB can
        # validate it. Keep all JWKS caching in the shared Django cache below.
        kwargs["cache_jwk_set"] = False
        super().__init__(uri, **kwargs)
        self.cache_timeout = kwargs.get("lifespan", 300)
        self._cache_namespace = hashlib.sha256(uri.encode()).hexdigest()
        self.forced_refresh_cooldown = self._configured_refresh_cooldown()
        # A fetch lease must outlive the originating HTTP request. Followers
        # use the same explicit JWKS timeout as the fetch owner, rather than
        # an unrelated request-worker timeout.
        self.fetch_wait_seconds = self.timeout
        self.fetch_lease_seconds = self.fetch_wait_seconds + 1

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
        return f"jwk_set:{self._cache_namespace}"

    @property
    def _refresh_lock_key(self) -> str:
        """Return the cooldown key that throttles forced key-set refreshes."""
        return f"jwks_refresh:{self._cache_namespace}"

    @property
    def _fetch_lock_key(self) -> str:
        """Return the short-lived lock used while one request fetches a JWKS document."""
        return f"jwks_fetch:{self._cache_namespace}"

    def _signing_key_cache_key(self, kid: str) -> str:
        """Return a cache key that safely scopes an individual signing key to this URI."""
        cache_identifier = hashlib.sha256(kid.encode()).hexdigest()
        return f"jwk:{self._cache_namespace}:{cache_identifier}"

    @staticmethod
    def _parse_jwk_set(document: Any) -> PyJWKSet:
        """Parse a provider document, rejecting non-objects and unusable JWKS documents."""
        if not isinstance(document, dict):
            raise PyJWKClientError("The JWKS endpoint did not return a JSON object")
        try:
            return PyJWKSet.from_dict(document)
        except PyJWKSetError as exc:
            raise PyJWKClientError("The JWKS endpoint returned an unusable key set") from exc

    def _fetch_and_cache_jwk_set(self) -> PyJWKSet:
        """Fetch, validate, and cache a JWKS document while holding the fetch lease."""
        document = super().fetch_data()
        jwk_set = self._parse_jwk_set(document)
        cache.set(self._jwk_set_cache_key, document, timeout=self.cache_timeout)
        return jwk_set

    def _acquire_fetch_lock(self, use_locks: bool) -> str:
        """Acquire the normal fetch lease and return its ownership token."""
        fetch_owner = str(uuid4())
        if use_locks and not cache.add(self._fetch_lock_key, fetch_owner, timeout=self.fetch_lease_seconds):
            raise _JWKSRetry
        return fetch_owner

    def _release_fetch_lock(self, owner: str, use_locks: bool) -> None:
        """Release a fetch lease only when it is still owned by this request.

        A lease can expire while an upstream request is slow. Checking its token
        prevents that original request from deleting a later request's lease.
        The lease exceeds the configured JWKS HTTP timeout, so a live owner
        releases it before expiry under normal operation.
        """
        if use_locks and cache.get(self._fetch_lock_key) == owner:
            cache.delete(self._fetch_lock_key)

    def _set_refresh_lock(self, use_locks: bool) -> None:
        """Start the forced-refresh cooldown without affecting normal fetch coordination.

        Unlike a fetch lease, the cooldown marker is deliberately not released;
        it expires naturally so unknown or rotated keys cannot trigger repeated
        provider refreshes.
        """
        if use_locks and not cache.add(self._refresh_lock_key, True, timeout=self.forced_refresh_cooldown):
            raise _JWKSRetry

    def _fetch_jwk_set_with_fetch_lock(self, use_locks: bool) -> PyJWKSet:
        """Fetch the JWK set when this request owns the normal fetch lease."""
        fetch_owner = self._acquire_fetch_lock(use_locks)

        try:
            return self._fetch_and_cache_jwk_set()
        finally:
            self._release_fetch_lock(fetch_owner, use_locks)

    @staticmethod
    def _sleep_before_jwk_set_retry(deadline: float, retry_count: int) -> None:
        """Back off with jitter or report fetch coordination failure."""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise JWKSFetchTimeoutError("Timed out waiting for a coordinated JWKS fetch")

        maximum_delay = min(MAX_JWKS_FETCH_RETRY_SECONDS, INITIAL_JWKS_FETCH_RETRY_SECONDS * 2**retry_count)
        delay = min(random.uniform(maximum_delay / 2, maximum_delay), remaining)
        time.sleep(delay)

    def get_jwk_set(self, refresh: bool = False) -> PyJWKSet:
        """Override PyJWT JWKS lookup to share provider keys and refresh coordination through Django's cache."""
        use_locks = self.forced_refresh_cooldown > 0
        deadline = time.monotonic() + self.fetch_wait_seconds
        need_to_acquire_refresh_lock = refresh
        retry_count = 0
        while True:
            try:
                if need_to_acquire_refresh_lock:
                    # Forced refreshes intentionally bypass a valid shared
                    # JWKS. Keep this cooldown marker after the fetch
                    # completes to throttle them.
                    self._set_refresh_lock(use_locks)
                    need_to_acquire_refresh_lock = False
                if not refresh and (document := cache.get(self._jwk_set_cache_key)) is not None:
                    return self._parse_jwk_set(document)
                return self._fetch_jwk_set_with_fetch_lock(use_locks)
            except _JWKSRetry:
                self._sleep_before_jwk_set_retry(deadline, retry_count)
                retry_count += 1

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
            raise PyJWKClientError("JWKS refresh is on cooldown")

        cache.delete(self._signing_key_cache_key(kid))
        signing_keys = self.get_signing_keys(refresh=True)
        signing_key = self.match_kid(signing_keys, kid)
        if not signing_key:
            raise PyJWKClientError(f"Unable to find a signing key that matches: {kid}")
        cache.set(self._signing_key_cache_key(kid), signing_key._jwk_data, timeout=self.cache_timeout)
        return signing_key
