import hashlib

from django.core.cache import cache
from jwt import PyJWK, PyJWKClient, get_unverified_header
from jwt.exceptions import PyJWKClientError, PyJWKError


class CachedJWKClient(PyJWKClient):
    """Adds a shared Django-cache layer to PyJWT's normal JWKS handling."""

    forced_refresh_cooldown = 30

    def __init__(self, uri, **kwargs):
        super().__init__(uri, **kwargs)
        self.cache_timeout = kwargs.get("lifespan", 300)
        self._cache_namespace = hashlib.sha256(uri.encode()).hexdigest()

    def get_signing_key_from_jwt(self, token):
        kid = get_unverified_header(token).get("kid")
        if not kid:
            return super().get_signing_key_from_jwt(token)

        cache_identifier = hashlib.sha256(kid.encode()).hexdigest()
        cache_key = f"external_oauth_jwk:{self._cache_namespace}:{cache_identifier}"
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

    def get_signing_key(self, kid):
        signing_keys = self.get_signing_keys()
        signing_key = self.match_kid(signing_keys, kid)
        if signing_key:
            return signing_key

        refresh_key = f"external_oauth_jwks_refresh:{self._cache_namespace}"
        if not cache.add(refresh_key, True, timeout=self.forced_refresh_cooldown):
            raise PyJWKClientError(f"Unable to find a signing key that matches: {kid}")

        signing_keys = self.get_signing_keys(refresh=True)
        signing_key = self.match_kid(signing_keys, kid)
        if signing_key:
            return signing_key

        raise PyJWKClientError(f"Unable to find a signing key that matches: {kid}")
