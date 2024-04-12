from django.conf import settings
import jwt
from typing import TypedDict
from ansible_base.resource_registry.models import service_id
from datetime import datetime, timedelta


class ResourceServerConfig(TypedDict):
    URL: str
    SECRET_KEY: str
    VALIDATE_HTTPS: bool
    JWT_ALGORITHM: str


def get_resource_server_config() -> ResourceServerConfig:
    defaults = {"JWT_ALGORITHM": "HS256", "VALIDATE_HTTPS": True}
    return ResourceServerConfig(**{**defaults, **settings.RESOURCE_SERVER})


def get_service_token(user_id, expiration=60):
    config = get_resource_server_config()
    payload = {
        "service_id": str(service_id()),
        "user_id": str(user_id),
    }

    if expiration is not None:
        payload["exp"] = datetime.now() + timedelta(seconds=expiration)

    return jwt.encode(payload, config["SECRET_KEY"], config["JWT_ALGORITHM"])
