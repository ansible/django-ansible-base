import logging

from rest_framework.serializers import ValidationError

from ansible_base.models import Authenticator, AuthenticatorUser
from ansible_base.utils.settings import get_setting
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

    try:
        login_redirect_override = get_setting('LOGIN_REDIRECT_OVERRIDE', None)
        validate_url(url=login_redirect_override, allow_plain_hostname=True)
        response['login_redirect_override'] = login_redirect_override
    except ValidationError:
        logger.exception('LOGIN_REDIRECT_OVERRIDE was set but was not a valid URL, ignoring')

    return response


def is_external_account(user) -> bool:
    # True if the user is associated with any external login source
    # False if the user is associated only with the local
    # None if there is no user

    if not user:
        return None

    authenticator_users = AuthenticatorUser.objects.filter(user_id=user.id)
    for auth_user in authenticator_users:
        provider = auth_user.provider
        if provider.type != 'ansible_base.authenticator_plugins.local':
            return True

    # This user was not associated with any providers that were not the local provider
    return False
