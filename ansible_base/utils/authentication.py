import importlib
import logging

from django.conf import settings
from rest_framework.serializers import ValidationError

from ansible_base.models import Authenticator
from ansible_base.utils.validation import validate_url

logger = logging.getLogger('ansible_base.utils.authentication')


def generate_ui_auth_data():
    authenticators = Authenticator.objects.filter(enabled=True)
    response = {
        'show_login_form': False,
        'passwords': [],
        'ssos': [],
        'login_redirect_override': '',
    }

    for authenticator in authenticators:
        if authenticator.category == 'password':
            response['show_login_form'] = True
            response['passwords'].append(
                {
                    'name': authenticator.name,
                    'type': authenticator.type,
                }
            )
        elif authenticator.category == 'sso':
            response['ssos'].append(
                {
                    'name': authenticator.name,
                    'login_url': authenticator.get_login_url(),
                    'type': authenticator.type,
                }
            )
        else:
            logger.error(f"Don't know how to handle authenticator of type {authenticator.type}")

    if hasattr(settings, 'LOGIN_REDIRECT_OVERRIDE'):
        try:
            validate_url(url=settings.LOGIN_REDIRECT_OVERRIDE, allow_plain_hostname=True)
            response['login_redirect_override'] = settings.LOGIN_REDIRECT_OVERRIDE
        except ValidationError:
            # Maybe we are pointing to function
            try:
                module_name, _, function_name = settings.LOGIN_REDIRECT_OVERRIDE.rpartition('.')
                the_function = getattr(importlib.import_module(module_name), function_name)
                redirect_url = the_function()
                response['login_redirect_override'] = redirect_url
            except Exception:
                logger.exception('LOGIN_REDIRECT_OVERRIDE was set but was not a valid URL and calling it as a function failed (see exception), ignoring')

    return response
