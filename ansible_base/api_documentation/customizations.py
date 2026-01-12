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
    """Register OAuth2 authentication extension for schema generation"""
    try:
        from drf_spectacular.extensions import OpenApiAuthenticationExtension
        from drf_spectacular.openapi import AutoSchema
        from drf_spectacular.settings import spectacular_settings

        from ansible_base.oauth2_provider.authentication import LoggedOAuth2Authentication

    except ImportError:
        # If dependencies aren't available, skip OAuth2 schema registration
        return

    class OAuth2Scheme(OpenApiAuthenticationExtension):
        """OAuth2 authentication scheme for LoggedOAuth2Authentication

        We must define a custom OpenApiAuthenticationExtension subclass, as
        drf-spectacular's built-in OAuth2 extension only targets the base OAuth2Authentication class
        Reads configuration from SPECTACULAR_SETTINGS OAUTH2_* keys.
        """

        target_class = LoggedOAuth2Authentication
        name = 'OAuth2_Authentication'
        priority = 1  # Needed to prevent built-in extensions overwriting the definition

        def get_security_definition(self, auto_schema: AutoSchema):
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

            return {'type': 'oauth2', 'flows': flows}
