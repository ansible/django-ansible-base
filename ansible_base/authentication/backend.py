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

    for database_authenticator in Authenticator.objects.filter(enabled=True):
        try:
            authentication_backends[database_authenticator.id] = get_authenticator_plugin(database_authenticator.type)
        except ImportError:
            continue
        authenticator_object = authentication_backends[database_authenticator.id]
        authenticator_object.update_if_needed(database_authenticator)
    return authentication_backends


class AnsibleBaseAuth(ModelBackend):
    def authenticate(self, request, *args, **kwargs):
        logger.debug("Starting AnsibleBaseAuth authentication")

        # Query the database for the most recently last modified timestamp.
        # This will be used as a cache key for the cached function get_authentication_backends below
        last_modified_item = Authenticator.objects.values("modified_on").order_by("-modified_on").first()
        last_modified = None if last_modified_item is None else last_modified_item.get('modified_on')

        for authenticator_id, authenticator_object in get_authentication_backends(last_modified).items():
            user = authenticator_object.authenticate(request, *args, **kwargs)
            if user:
                # The local authenticator handles this but we want to check this for other authentication types
                if not getattr(user, 'is_active', True):
                    logger.warning(
                        f'User {user.username} attempted to login from authenticator with ID "{authenticator_id}" their user is inactive, denying permission'
                    )
                    return None

                logger.info(f'User {user.username} logged in from authenticator with ID "{authenticator_id}"')
                authenticator_object.database_instance.users.add(user)
                return user

        return None
