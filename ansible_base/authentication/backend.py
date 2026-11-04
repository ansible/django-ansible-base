import logging
from functools import lru_cache

from django.contrib.auth.backends import ModelBackend

from ansible_base.authentication.authenticator_cache import get_authenticator_cache_version, load_authenticator_plugins
from ansible_base.authentication.models import Authenticator
from ansible_base.lib.logging import log_auth_event, log_auth_exception, log_auth_warning

logger = logging.getLogger('ansible_base.authentication.backend')


@lru_cache(maxsize=1)
def get_authentication_backends(cache_version):
    # cache_version is primarily here as a cache busting mechanism
    authenticators = Authenticator.objects.filter(enabled=True).exclude(category="api_auth").order_by("order")
    return load_authenticator_plugins(authenticators)


class AnsibleBaseAuth(ModelBackend):
    def authenticate(self, request, *args, **kwargs):
        from ansible_base.authentication.social_auth import SOCIAL_AUTH_PIPELINE_FAILED_STATUS

        logger.debug("Starting AnsibleBaseAuth authentication")

        # Query the shared database for a version used to invalidate this
        # process-local cache across all Gateway workers.
        cache_version = get_authenticator_cache_version(Authenticator.objects.exclude(category="api_auth"))

        for authenticator_id, authenticator_object in get_authentication_backends(cache_version).items():
            try:
                user = authenticator_object.authenticate(request, *args, **kwargs)
            except Exception:
                log_auth_exception(f"Exception raised while trying to authenticate with {authenticator_object.database_instance.name}")
                continue

            # Social Auth pipeline can return status string when update_user_claims fails (authentication maps deny access)
            if user == SOCIAL_AUTH_PIPELINE_FAILED_STATUS:
                continue

            if user:
                # The local authenticator handles this but we want to check this for other authentication types
                if not getattr(user, 'is_active', True):
                    log_auth_warning(
                        f'User {user.username} attempted to login from authenticator with ID "{authenticator_id}" their user is inactive, denying permission'
                    )
                    return None

                log_auth_event(f'User {user.username} logged in from {authenticator_object.type} authenticator with ID "{authenticator_id}"')
                if hasattr(user, "last_login_from"):
                    user.last_login_from = authenticator_object.database_instance
                    user.save(update_fields=['last_login_from'])
                return user
        provided_username = kwargs.get('username', 'Unknown')
        log_auth_event(f"Authentication failed for username: {provided_username}")
        return None
