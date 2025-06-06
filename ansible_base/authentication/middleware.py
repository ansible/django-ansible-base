import logging
from collections import defaultdict
from urllib.parse import urlsplit

from django.contrib.auth import BACKEND_SESSION_KEY
from django.core.exceptions import ImproperlyConfigured
from django.middleware.csrf import CsrfViewMiddleware
from django.utils.deprecation import MiddlewareMixin
from django.utils.functional import cached_property
from social_django.middleware import SocialAuthExceptionMiddleware

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugins
from ansible_base.lib.utils.settings import get_setting

logger = logging.getLogger('ansible_base.authentication.middleware')


def get_authenticator_module_paths() -> list:
    plugins = get_authenticator_plugins()
    plugins = [f'{name}.AuthenticatorPlugin' for name in plugins]
    return plugins


class AuthenticatorBackendMiddleware(MiddlewareMixin):
    _plugins = None

    @property
    def plugins(self):
        if not self._plugins:
            self._plugins = get_authenticator_module_paths()
        return self._plugins

    def process_request(self, request):
        if not hasattr(request, "session"):
            raise ImproperlyConfigured(
                "The Django AuthenticatorBackendMiddleware requires session "
                "middleware to be installed. Edit your MIDDLEWARE setting to "
                "insert "
                "'django.contrib.sessions.middleware.SessionMiddleware' before "
                "'AuthenticatorBackendMiddleware'."
            )

        # If the session backend is one from one of the Authenticator plugins, change it to
        # ansible_base.authentication.backend.AnsibleBaseAuth so that the user can be logged
        # in since the Authenticator backends aren't in AUTHENTICATION_BACKENDS
        if backend := request.session.get(BACKEND_SESSION_KEY, None):
            if backend in self.plugins:
                request.session[BACKEND_SESSION_KEY] = "ansible_base.authentication.backend.AnsibleBaseAuth"


class SocialExceptionHandlerMiddleware(SocialAuthExceptionMiddleware):
    def get_redirect_uri(self, request, exception):
        strategy = getattr(request, "social_strategy", None)
        error_url = strategy.setting("LOGIN_ERROR_URL")
        backend = getattr(request, "backend", None)
        backend_name = getattr(backend, "name", "unknown-backend")
        logger.error(f"Auth failure for backend {backend_name} - {repr(exception)}, redirecting to {error_url}")
        return error_url


class AnsibleBaseCsrfViewMiddleware(CsrfViewMiddleware):
    """
    CsrfViewMiddleware subclass that reads CSRF_TRUSTED_ORIGINS using
    ansible_base.lib.utils.settings.get_setting instead of directly from
    Django settings.

    This allows the setting to be dynamically loaded from various sources
    as configured by the ANSIBLE_BASE_SETTINGS_FUNCTION setting.

    Overrides all cached properties that access settings.CSRF_TRUSTED_ORIGINS
    to use get_setting instead.
    """

    @cached_property
    def csrf_trusted_origins_hosts(self):
        """
        Override to use get_setting instead of settings.CSRF_TRUSTED_ORIGINS.
        """
        csrf_trusted_origins = get_setting('CSRF_TRUSTED_ORIGINS', [])
        return [urlsplit(origin).netloc.lstrip("*") for origin in csrf_trusted_origins]

    @cached_property
    def allowed_origins_exact(self):
        """
        Override to use get_setting instead of settings.CSRF_TRUSTED_ORIGINS.
        """
        csrf_trusted_origins = get_setting('CSRF_TRUSTED_ORIGINS', [])
        return {origin for origin in csrf_trusted_origins if "*" not in origin}

    @cached_property
    def allowed_origin_subdomains(self):
        """
        Override to use get_setting instead of settings.CSRF_TRUSTED_ORIGINS.
        A mapping of allowed schemes to list of allowed netlocs, where all
        subdomains of the netloc are allowed.
        """
        csrf_trusted_origins = get_setting('CSRF_TRUSTED_ORIGINS', [])
        allowed_origin_subdomains = defaultdict(list)
        for parsed in (urlsplit(origin) for origin in csrf_trusted_origins if "*" in origin):
            allowed_origin_subdomains[parsed.scheme].append(parsed.netloc.lstrip("*"))
        return allowed_origin_subdomains
