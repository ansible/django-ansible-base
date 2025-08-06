import logging
from typing import Optional, Tuple

from django.conf import settings
from django.core.cache import caches

from ansible_base.lib.utils.settings import get_setting

logger = logging.getLogger('ansible_base.jwt_consumer.common.cache')


# This setting allows a service to override which django cache we want to use
jwt_cache_name = getattr(settings, 'ANSIBLE_BASE_JWT_CACHE_NAME', 'default')
cache = caches[jwt_cache_name]
# This is the cache name we will use for the JWT key
cache_key = 'ansible_base_jwt_public_key'


class JWTCache:
    def get_cache_timeout(self):
        # If unspecified the cache will expire in 7 days
        cache_timeout = get_setting('ANSIBLE_BASE_JWT_CACHE_TIMEOUT_SECONDS', 604800)
        return cache_timeout

    def check_user_in_cache(self, validated_body: dict) -> Tuple[bool, dict]:
        # These are the defaults which will get passed to the user creation and what we expect in the cache
        expected_cache_value = {
            "first_name": validated_body['user_data']["first_name"],
            "last_name": validated_body['user_data']["last_name"],
            "email": validated_body['user_data']["email"],
            "is_superuser": validated_body['user_data']["is_superuser"],
        }
        cached_user = cache.get(validated_body["sub"], None)
        # If the user was in the cache and the values of the cache match the expected values we had it in cache
        if cached_user is not None and cached_user == expected_cache_value:
            return True, expected_cache_value
        # The user was not previously in the cache, set the user in the cache so it is found on future requests
        cache.set(validated_body["sub"], expected_cache_value, timeout=self.get_cache_timeout())
        return False, expected_cache_value

    def get_key_from_cache(self) -> Optional[str]:
        # If we are not ignoring the cache (forcing a reload of the key), check it
        key = cache.get(cache_key, None)
        logger.debug(f"Cached key is {key}")
        return key

    def set_key_in_cache(self, key: str) -> None:
        cache.set(cache_key, key, timeout=self.get_cache_timeout())

    def get_claims_hash(self, user_ansible_id: str) -> Optional[str]:
        """Get cached claims hash for a user."""
        claims_hash_key = f"jwt_claims_hash_{user_ansible_id}"
        return cache.get(claims_hash_key, None)

    def set_claims_hash(self, user_ansible_id: str, claims_hash: str) -> None:
        """Set cached claims hash for a user."""
        claims_hash_key = f"jwt_claims_hash_{user_ansible_id}"
        cache.set(claims_hash_key, claims_hash, timeout=self.get_cache_timeout())

    def get_cached_claims(self, user_ansible_id: str) -> Optional[dict]:
        """Get cached gateway claims for a user."""
        claims_key = f"jwt_gateway_claims_{user_ansible_id}"
        return cache.get(claims_key, None)

    def set_cached_claims(self, user_ansible_id: str, claims: dict) -> None:
        """Set cached gateway claims for a user."""
        claims_key = f"jwt_gateway_claims_{user_ansible_id}"
        cache.set(claims_key, claims, timeout=self.get_cache_timeout())
