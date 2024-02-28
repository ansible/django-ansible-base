import logging
from collections import OrderedDict

from django.contrib.auth.backends import ModelBackend

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugin
from ansible_base.authentication.models import Authenticator

logger = logging.getLogger('ansible_base.authentication.backend')

authentication_backends = OrderedDict()
last_authenticator_update = None


def update_authenticator_cache():
    global last_authenticator_update
    global authentication_backends
    last_modified = Authenticator.objects.values("modified_on").order_by("-modified_on").first()["modified_on"]

    if last_modified == last_authenticator_update:
        return

    last_authenticator_update = last_modified
    authentication_backends = OrderedDict()

    for database_authenticator in Authenticator.objects.filter(enabled=True):
        authentication_backends[database_authenticator.id] = get_authenticator_plugin(database_authenticator.type)
        authenticator_object = authentication_backends[database_authenticator.id]
        authenticator_object.update_if_needed(database_authenticator)


class AnsibleBaseAuth(ModelBackend):
    def authenticate(self, request, *args, **kwargs):
        logger.debug("Starting AnsibleBaseAuth authentication")
        update_authenticator_cache()
        for k, authenticator_object in authentication_backends.items():
            user = authenticator_object.authenticate(request, *args, **kwargs)
            if user:
                # The local authenticator handles this but we want to check this for other authentication types
                if not getattr(user, 'is_active', True):
                    logger.warning(f'User {user.username} attempted to login from authenticator with ID "{k}" their user is inactive, denying permission')
                    return None

                logger.info(f'User {user.username} logged in from authenticator with ID "{k}"')
                authenticator_object.database_instance.users.add(user)
                return user

        return None
