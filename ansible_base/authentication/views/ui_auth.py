import logging


from django.utils.translation import gettext_lazy as _
from django.conf import settings

from rest_framework.response import Response
from rest_framework.serializers import ValidationError

from ansible_base.authentication.models import Authenticator
from ansible_base.lib.utils.settings import get_setting
from ansible_base.lib.utils.validation import to_python_boolean, validate_image_data, validate_url
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView

logger = logging.getLogger('ansible_base.authentication.views.ui_auth')


class UIAuth(AnsibleBaseDjangoAppApiView):
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
        'managed_cloud_install': False,
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
            try:
                response['ssos'].append(
                    {
                        'name': authenticator.name,
                        'login_url': authenticator.get_login_url(),
                        'type': authenticator.type,
                    }
                )
            except ImportError:
                logger.error(f"There is an enabled authenticator id {authenticator.id} whose plugin is not working {authenticator.type}")
        else:
            logger.error(f"Don't know how to handle authenticator of type {authenticator.type}")

    try:
        login_redirect_override = get_setting('LOGIN_REDIRECT_OVERRIDE', '')
        # ignore validation if login_redirect_override is None or empty string
        if login_redirect_override is not None and login_redirect_override != '':
            validate_url(url=login_redirect_override, allow_plain_hostname=True)
            response['login_redirect_override'] = login_redirect_override
    except ValidationError:
        logger.error('LOGIN_REDIRECT_OVERRIDE was set but was not a valid URL, ignoring')

    custom_login_info = get_setting('custom_login_info', '')
    if isinstance(custom_login_info, str):
        response['custom_login_info'] = custom_login_info
    else:
        logger.error("custom_login_info was not a string")
        raise ValidationError(_("custom_login_info was set but was not a valid string, ignoring"))

    try:
        custom_logo = get_setting('custom_logo', '')
        validate_image_data(custom_logo)
        response['custom_logo'] = custom_logo
    except ValidationError:
        logger.error("custom_logo was set but was not a valid image data, ignoring")

    # The cloud managed setting is not customizable outside of a conf file
    managed_cloud_setting = 'ANSIBLE_BASE_MANAGED_CLOUD_INSTALL'
    try:
        response['managed_cloud_install'] = to_python_boolean(getattr(settings, managed_cloud_setting, False))
    except ValueError:
        logger.error(f'{managed_cloud_setting} was set but could not be converted to a boolean, assuming false')

    return response
