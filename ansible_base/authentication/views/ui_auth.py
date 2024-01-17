import logging

from rest_framework.response import Response
from rest_framework.serializers import ValidationError
from rest_framework.views import APIView

from ansible_base.authentication.models import Authenticator
from ansible_base.common.utils.settings import get_setting
from ansible_base.common.utils.validation import validate_image_data, validate_url

logger = logging.getLogger('ansible_base.authentication.views.ui_auth')


class UIAuth(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, format=None):
        response = generate_ui_auth_data()

        return Response(response)


def generate_ui_auth_data():
    authenticators = Authenticator.objects.filter(enabled=True)
    response = {
        'show_login_form': False,
        'passwords': [],
        'ssos': [],
        'login_redirect_override': '',
        'custom_login_info': '',
        'custom_logo': '',
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

    custom_login_info = get_setting('custom_login_info', '')
    if isinstance(custom_login_info, str):
        response['custom_login_info'] = custom_login_info
    else:
        logger.exception("custom_login_info was not a string")
        raise ValidationError("custom_login_info was set but was not a valid string, ignoring")

    try:
        custom_logo = get_setting('custom_logo', '')
        validate_image_data(custom_logo)
        response['custom_logo'] = custom_logo
    except ValidationError:
        logger.exception("custom_logo was set but was not a valid image data, ignoring")

    return response
