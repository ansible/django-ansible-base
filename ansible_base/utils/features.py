from django.conf import settings

AUTHENTICATION = 'AUTHENTICATION'
FILTERING = 'FILTERING'
OAUTH2_PROVIDER = 'OAUTH2_PROVIDER'
SWAGGER = 'SWAGGER'


def feature_enabled(name: str) -> bool:
    features_hash = getattr(settings, 'ANSIBLE_BASE_FEATURES', {})
    return features_hash.get(name, False)
