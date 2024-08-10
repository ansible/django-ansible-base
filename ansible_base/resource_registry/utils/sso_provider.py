try:
    from social_core.backends.oauth import OAuthAuth
    from social_core.backends.saml import SAMLAuth
    from social_django.utils import load_strategy
except ImportError:
    load_strategy = None


def get_sso_provider_server(backend_name: str, uid: str):
    """
    Returns the hostname for the SSO server that authenticated this user.
    """
    if load_strategy is None:
        return None

    social_strat = load_strategy()

    try:
        backend = social_strat.get_backend(backend_name)
    except TypeError:
        return (None, uid)

    if isinstance(backend, SAMLAuth):
        idp, real_uid = uid.split(":", maxsplit=1)
        return (backend.get_idp(idp).entity_id, real_uid)

    elif isinstance(backend, OAuthAuth):
        return (backend.authorization_url(), uid)
    else:
        return (None, uid)
