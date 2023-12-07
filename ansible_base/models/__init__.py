from ansible_base.utils.settings import feature_enabled

from .authenticator import Authenticator  # noqa: 401
from .authenticator_map import AuthenticatorMap  # noqa: 401
from .social_auth import AuthenticatorUser  # noqa: 401

if feature_enabled('OAUTH2_PROVIDER'):
    from .oauth2_provider import OAuth2AccessToken, OAuth2Application, OAuth2IDToken, OAuth2RefreshToken  # noqa: 401
