from django.apps import AppConfig


class DABFallbackCacheConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base.cache'
    label = 'dab_fallback_cache'
