from social_core.backends.oauth import OAuthAuth
from social_core.backends.saml import SAMLAuth
from social_django.utils import load_strategy


def get_sso_provider_host(backend_name: str, uid: str):
    """
    Returns the hostname for the SSO server that authenticated this user.
    """
    social_strat = load_strategy()

    try:
        backend = social_strat.get_backend(backend_name)
    except TypeError:
        return (None, uid)

    if isinstance(backend, SAMLAuth):
        idp, real_uid = uid.split(":", maxsplit=1)
        return (backend.get_idp(idp), real_uid)

    elif isinstance(backend, OAuthAuth):
        return (backend.setting("AUTHORIZATION_URL"), uid)
    else:
        return (None, uid)
