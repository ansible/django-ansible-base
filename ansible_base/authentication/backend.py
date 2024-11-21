import logging
from collections import OrderedDict
from functools import lru_cache

from django.contrib.auth.backends import ModelBackend

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugin
from ansible_base.authentication.models import Authenticator

logger = logging.getLogger('ansible_base.authentication.backend')


@lru_cache(maxsize=1)
def get_authentication_backends(last_updated):
    # last_updated is primarily here as a cache busting mechanism
    authentication_backends = OrderedDict()

    for database_authenticator in Authenticator.objects.filter(enabled=True).order_by('order'):
        try:
            authentication_backends[database_authenticator.id] = get_authenticator_plugin(database_authenticator.type)
        except ImportError:
            continue
        authenticator_object = authentication_backends[database_authenticator.id]
        authenticator_object.update_if_needed(database_authenticator)
    return authentication_backends


class AnsibleBaseAuth(ModelBackend):
    def authenticate(self, request, *args, **kwargs):
        from ansible_base.authentication.social_auth import SOCIAL_AUTH_PIPELINE_FAILED_STATUS

        logger.debug("Starting AnsibleBaseAuth authentication")

        # Query the database for the most recently last modified timestamp.
        # This will be used as a cache key for the cached function get_authentication_backends below
        last_modified_item = Authenticator.objects.values("modified").order_by("-modified").first()
        last_modified = None if last_modified_item is None else last_modified_item.get('modified')

        for authenticator_id, authenticator_object in get_authentication_backends(last_modified).items():
            try:
                user = authenticator_object.authenticate(request, *args, **kwargs)
            except Exception:
                logger.exception(f"Exception raised while trying to authenticate with {authenticator_object.database_instance.name}")
                continue

            # Social Auth pipeline can return status string when update_user_claims fails (authentication maps deny access)
            if user == SOCIAL_AUTH_PIPELINE_FAILED_STATUS:
                continue

            if user:
                # The local authenticator handles this but we want to check this for other authentication types
                if not getattr(user, 'is_active', True):
                    logger.warning(
                        f'User {user.username} attempted to login from authenticator with ID "{authenticator_id}" their user is inactive, denying permission'
                    )
                    return None

                logger.info(f'User {user.username} logged in from authenticator with ID "{authenticator_id}"')
                return user
        return None
