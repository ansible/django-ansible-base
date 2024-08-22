from datetime import datetime, timedelta

import jwt

from ansible_base.resource_registry.models import Resource, service_id
from ansible_base.resource_registry.resource_server import get_resource_server_config
from ansible_base.resource_registry.utils.sso_provider import get_sso_provider_server


def get_user_auth_code(user, social_user=None):
    """
    Generate an authentication code using the service's configured secret key.

    user: Django User instance
    social_user: SocialUser or AuthenticatorUser instance for the backend used to authenticate the user.
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
        "sso_server": None,
    }

    if social_user is not None:

        if isinstance(social_user.provider, str):
            provider = social_user.provider
        else:
            provider = social_user.provider.slug

        server, uid = get_sso_provider_server(provider, social_user.uid)

        payload["sso_uid"] = uid
        payload["sso_backend"] = provider
        payload["sso_server"] = server

    return jwt.encode(payload, config["SECRET_KEY"], config["JWT_ALGORITHM"])
