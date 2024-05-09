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
