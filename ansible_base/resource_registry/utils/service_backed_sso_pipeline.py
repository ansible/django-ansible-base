from django.conf import settings
from django.shortcuts import redirect

from ansible_base.resource_registry.resource_server import get_resource_server_config
from ansible_base.resource_registry.utils.auth_code import get_user_auth_code


def redirect_to_resource_server(*args, social=None, user=None, **kwargs):
    """
    This MUST come at the end of the SOCIAL_AUTH_PIPELINE configuration.
    """

    if not user:
        return None

    redirect_path = getattr(settings, 'SERVICE_BACKED_SSO_AUTH_CODE_REDIRECT_PATH', '/login/')
    redirect_url = getattr(
        settings,
        'SERVICE_BACKED_SSO_AUTH_CODE_REDIRECT_URL',
        get_resource_server_config()["URL"],
    )

    auth_code = get_user_auth_code(user, social_user=social)
    url = redirect_url + redirect_path + "?auth_code=" + auth_code

    return redirect(url, permanent=False)
