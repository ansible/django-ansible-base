from social_core.utils import user_is_active, user_is_authenticated
from social_django.strategy import DjangoStrategy

from ansible_base.resource_registry.resource_server import get_resource_server_config, get_user_auth_code


# Turning this into a mixin so that we can use it with other Stategy base classes when
# we need to.
class AuthCodeRedirectMixin:
    """
    This mixin commandeers the redirect method on the DjangoStrategy class and redirects
    the user to the resource server with an auth code generated using the configured
    secret key, if the user has just logged in with social auth.
    """

    def redirect(self, url):
        user = self.request.user
        if user_is_authenticated(user) and user_is_active(user) and hasattr(user, "social_user"):
            auth_code = get_user_auth_code(user)
            url = get_resource_server_config()["URL"] + "/api/gateway/v1/validate_auth_code/?auth_code=" + auth_code

        return super().redirect(url)


class ResourceServerRedirectStrategy(AuthCodeRedirectMixin, DjangoStrategy):
    """
    Generate an auth code and redirect to the resource server when a user authenticates
    via social auth.
    """

    pass
