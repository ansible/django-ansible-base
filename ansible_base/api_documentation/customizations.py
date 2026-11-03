from typing import Any


def get_dab_lib_doc_excludes():
    """Extend drf-spectacular's docstring boundary with DAB mixins."""
    from drf_spectacular.plumbing import get_lib_doc_excludes

    from ansible_base.lib.serializers.mixins import CleanTextMixin

    return [*get_lib_doc_excludes(), CleanTextMixin]


def apply_authentication_customizations() -> None:
    """Declare schema of DAB authentication classes

    This follows docs which reccomends OpenApiAuthenticationExtension to register an authentication class
    https://drf-spectacular.readthedocs.io/en/latest/customization.html#specify-authentication-with-openapiauthenticationextension
    As long as this class is resolved on import, drf-spectacular will be aware of it.
    This is called from api_documentation ready method.
    Imports are in-line, because dependencies may not be satisfied depending on what apps are installed.
    """
    from drf_spectacular.authentication import SessionScheme

    from ansible_base.authentication.session import SessionAuthentication

    class MyAuthenticationScheme(SessionScheme):
        target_class = SessionAuthentication
        name = 'SessionAuthentication'


def apply_oauth2_customizations() -> None:
    """Register the available Bearer authentication schemas for OpenAPI generation."""
    try:
        from drf_spectacular.extensions import OpenApiAuthenticationExtension
        from drf_spectacular.openapi import AutoSchema
        from drf_spectacular.settings import spectacular_settings
    except ImportError:
        # If dependencies aren't available, skip authentication schema registration.
        return

    from django.conf import settings

    authentication_installed = 'ansible_base.authentication' in settings.INSTALLED_APPS
    oauth2_provider_installed = 'ansible_base.oauth2_provider' in settings.INSTALLED_APPS
    if not authentication_installed and not oauth2_provider_installed:
        return

    scheme_names: list[str] = []
    scheme_definitions: list[dict[str, Any]] = []
    target_authentication_class = None

    if authentication_installed:
        from ansible_base.authentication.bearer_authentication import BearerAuthentication

        target_authentication_class = BearerAuthentication
        scheme_names.append('BearerAuthentication')
        scheme_definitions.append({'type': 'http', 'scheme': 'bearer'})

    if oauth2_provider_installed:
        from ansible_base.oauth2_provider.authentication import LoggedOAuth2Authentication

        target_authentication_class = target_authentication_class or LoggedOAuth2Authentication
        flows = {}
        for flow_type in spectacular_settings.OAUTH2_FLOWS:
            flows[flow_type] = {}
            if flow_type in ('implicit', 'authorizationCode'):
                flows[flow_type]['authorizationUrl'] = spectacular_settings.OAUTH2_AUTHORIZATION_URL
            if flow_type in ('password', 'clientCredentials', 'authorizationCode'):
                flows[flow_type]['tokenUrl'] = spectacular_settings.OAUTH2_TOKEN_URL
            if spectacular_settings.OAUTH2_REFRESH_URL:
                flows[flow_type]['refreshUrl'] = spectacular_settings.OAUTH2_REFRESH_URL
            flows[flow_type]['scopes'] = spectacular_settings.OAUTH2_SCOPES or {}

        scheme_names.append('OAuth2_Authentication')
        scheme_definitions.append({'type': 'oauth2', 'flows': flows})

    class BearerAuthenticationScheme(OpenApiAuthenticationExtension):
        """Describe the active Bearer credentials without importing optional applications."""

        target_class = target_authentication_class
        name = scheme_names[0] if len(scheme_names) == 1 else scheme_names
        priority = 1  # Needed to prevent built-in extensions overwriting the definition.

        def get_security_definition(self, auto_schema: AutoSchema):
            if len(scheme_definitions) == 1:
                return scheme_definitions[0]
            return scheme_definitions

        def get_security_requirement(self, auto_schema: AutoSchema):
            if len(scheme_names) == 1:
                return super().get_security_requirement(auto_schema)
            return [{scheme_name: []} for scheme_name in scheme_names]
