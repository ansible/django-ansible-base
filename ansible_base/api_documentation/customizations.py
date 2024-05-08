def apply_authentication_customizations() -> None:
    """Make the schema generator of the type of DAB authentication classes"""
    from drf_spectacular.authentication import SessionScheme

    from ansible_base.authentication.session import SessionAuthentication

    class MyAuthenticationScheme(SessionScheme):
        target_class = SessionAuthentication  # full import path OR class ref
        name = 'SessionAuthentication'
