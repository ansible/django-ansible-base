from django.shortcuts import redirect

from ansible_base.resource_registry.resource_server import get_resource_server_config
from ansible_base.resource_registry.utils.auth_code import get_user_auth_code


def redirect_to_resource_server(*args, social=None, user=None, **kwargs):
    """
    This MUST come at the end of the SOCIAL_AUTH_PIPELINE configuration.
    """

    if not user:
        return None

    auth_code = get_user_auth_code(user, social_user=social)
    url = get_resource_server_config()["URL"] + "/api/gateway/v1/validate_auth_code/?auth_code=" + auth_code

    return redirect(url, permanent=False)
