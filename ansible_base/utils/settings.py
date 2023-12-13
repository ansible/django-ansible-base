from typing import Any

from django.conf import settings


def get_setting(name: str, default: Any) -> Any:
    return getattr(settings, name, default)


def feature_enabled(name: str) -> bool:
    features_hash = getattr(settings, 'ANSIBLE_BASE_FEATURES', {})
    return features_hash.get(name, False)
