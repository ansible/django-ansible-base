# The cache is also tested by test_auth and test_cert
from ansible_base.jwt_consumer.common.cache import JWTCache


def test_cache_claims_hash():
    cache = JWTCache()
    cache.cache_claims_hash('12345678-1234-5678-9abc-123456789012', 'a1b2c3d4')
    assert cache.get_cached_claims_hash('12345678-1234-5678-9abc-123456789012') == 'a1b2c3d4'
