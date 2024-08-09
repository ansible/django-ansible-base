from datetime import datetime, timedelta
from typing import TypedDict

import jwt
from django.conf import settings

from ansible_base.resource_registry.models import Resource, service_id


class ResourceServerConfig(TypedDict):
    URL: str
    SECRET_KEY: str
    VALIDATE_HTTPS: bool
    JWT_ALGORITHM: str


def get_resource_server_config() -> ResourceServerConfig:
    defaults = {"JWT_ALGORITHM": "HS256", "VALIDATE_HTTPS": True}
    defaults.update(settings.RESOURCE_SERVER)
    return defaults


def get_service_token(user_id=None, expiration=60, **kwargs):
    config = get_resource_server_config()
    payload = {
        "iss": str(service_id()),
        **kwargs,
    }

    if user_id is not None:
        payload["sub"] = user_id

    if expiration is not None:
        payload["exp"] = datetime.now() + timedelta(seconds=expiration)

    return jwt.encode(payload, config["SECRET_KEY"], config["JWT_ALGORITHM"])


def get_user_auth_code(user):
    """
    Generate an authentication code using the service's configured secret key.
    """
    config = get_resource_server_config()
    payload = {
        "iss": str(service_id()),
        "type": "auth_code",
        "username": user.username,
        "sub": str(Resource.get_resource_for_object(user).ansible_id),
        "exp": datetime.now() + timedelta(seconds=15),
        "sso_uid": None,
        "sso_backend": None,
    }

    if hasattr(user, "social_user"):
        payload["sso_uid"] = user.social_user.uid
        payload["sso_backend"] = user.social_user.provider

    return jwt.encode(payload, config["SECRET_KEY"], config["JWT_ALGORITHM"])
