import logging
from typing import Optional

from django.core import cache

from ansible_base.lib.utils.settings import get_setting

logger = logging.getLogger('ansible_base.features')


def feature_enabled(short_name: Optional[str]) -> bool:
    """
    Return a boolean indicating if the feature is enabled or not
    """

    # If we didn't get a name, there is not a related feature, just say No
    if not short_name:
        return False

    # Check the cache if possible
    feature_cache = get_feature_cache()
    if feature_cache:
        enabled = feature_cache.get(short_name)
        if enabled is not None:
            return enabled

    # We either didn't have cache or it wasn't set in the cache so check the models
    from ansible_base.features.models import Feature

    try:
        feature = Feature.objects.get(short_name=short_name)
        return feature.enabled
    except Feature.DoesNotExist:
        # There is no feature with that name so it can't be enabled
        return False


def get_feature_cache():
    feature_cache_name = get_setting('ANSIBLE_BASE_FEATURE_CACHE', None)
    if not feature_cache_name:
        return None

    try:
        return cache.caches[feature_cache_name]
    except cache.InvalidCacheBackendError:
        logger.exception(f'Configured feature cache {feature_cache_name} does not exist!')
