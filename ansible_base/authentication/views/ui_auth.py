import logging
from typing import Union

from django.conf import settings
from django.utils.translation import gettext_lazy as _
from rest_framework.response import Response
from rest_framework.serializers import ValidationError

from ansible_base.authentication.models import Authenticator
from ansible_base.authentication.serializers import UIAuthResponseSerializer
from ansible_base.lib.utils.settings import get_setting, is_aoc_instance
from ansible_base.lib.utils.validation import validate_absolute_path, validate_image_data, validate_url
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView

logger = logging.getLogger('ansible_base.authentication.views.ui_auth')


class UIAuth(AnsibleBaseDjangoAppApiView):
    authentication_classes = []
    permission_classes = []
    serializer_class = UIAuthResponseSerializer

    def _get(self):
        response = generate_ui_auth_data()
        return Response(response)

    # Conditionally add openapi documentation
    if 'ansible_base.api_documentation' in settings.INSTALLED_APPS:
        from drf_spectacular.utils import extend_schema

        @extend_schema(
            request=None, responses=UIAuthResponseSerializer, description="Get UI authentication configuration including available authenticators and settings."
        )
        def get(self, request, format=None):
            return self._get()

    else:

        def get(self):
            return self._get()


def _validate_and_get_login_redirect_override() -> Union[str, None]:
    try:
        login_redirect_override = get_setting('LOGIN_REDIRECT_OVERRIDE', '')
        # ignore validation if login_redirect_override is None or empty string
        if login_redirect_override is not None and login_redirect_override != '':
            validate_url(url=login_redirect_override, schemes=['https', 'http'], allow_plain_hostname=True)
            return login_redirect_override
    except ValidationError:
        # login_redirect_override can also be an absolute path
        try:
            validate_absolute_path(path=login_redirect_override)
            return login_redirect_override
        except ValidationError:
            logger.error('LOGIN_REDIRECT_OVERRIDE was set but was not a valid URL or absolute path, ignoring')
    return None


def generate_ui_auth_data():
    authenticators = Authenticator.objects.filter(enabled=True)
    response = {
        'passwords': [],
        'ssos': [],
        'show_login_form': False,
        'login_redirect_override': '',
        'custom_login_info': '',
        'custom_logo': '',
        'managed_cloud_install': False,
    }

    for authenticator in authenticators:
        if authenticator.category == 'password':
            response['passwords'].append(
                {
                    'name': authenticator.name,
                }
            )
            response["show_login_form"] = True
        elif authenticator.category == 'sso':
            try:
                response['ssos'].append({'name': authenticator.name, 'login_url': authenticator.get_login_url(), 'type': authenticator.type.split('.')[-1]})
                response["show_login_form"] = True
            except ImportError:
                logger.error(f"There is an enabled authenticator id {authenticator.id} whose plugin is not working {authenticator.type}")
        else:
            logger.error(f"Don't know how to handle authenticator of type {authenticator.type}")

    login_redirect_override = _validate_and_get_login_redirect_override()
    if login_redirect_override:
        response['login_redirect_override'] = login_redirect_override

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
    response['managed_cloud_install'] = is_aoc_instance()

    return response
