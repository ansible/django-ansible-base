# Fallback cache

The `django-ansible-base` package includes a fallback cache manager. This allow you to specify a primary and fallback cache and if the primary fails the fallback cache will be used until the primary cache recovers.

## Enabling fallback cache
To use the fallback cache do the following in your settings:

```python
CACHES = {
    "default": {
        "BACKEND": "ansible_base.lib.cache.fallback_cache.DABCacheWithFallback",
    },
    "primary": {
        "BACKEND": "django_redis.cache.RedisCache",
        ...
    },
    "fallback": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": "/var/tmp/django_cache",
    },
}
```

The `default` cache becomes a type `ansible_base.lib.cache.fallback_cache.DABCacheWithFallback`. We also add a `primary` and `fallback` caches.
Note, we don't recommend using a `LocMemCache` type as the fallback because you can end up with issues because each thread has its own copy of the cache.

The primary cache will be used until it fails. At that point:
* An indicator file will be created in your default temp location called gw_primary_cache_failed.
* The fallback cache will begin to be used.

While the fallback cache is operational, every request will:
* Pull values from that cache
* Spawn a thread to check and see if the primary cache is back online

If the primary cache comes back online:
* The primary cache will be cleared
* The indicator file will be removed
* The fallback cache will be cleared
* The primary cache will be used again
