import logging
from collections import OrderedDict

from django.contrib.auth.backends import ModelBackend

from ansible_base.authenticator_plugins.utils import get_authenticator_plugin
from ansible_base.models import Authenticator

logger = logging.getLogger('ansible_base.authentication.backend')

authentication_backends = OrderedDict()


class AnsibleBaseAuth(ModelBackend):
    def authenticate(self, request, *args, **kwargs):
        logger.info("Starting AnsibleBaseAuth authentication")

        for database_authenticator in Authenticator.objects.filter(enabled=True):
            # Either get the existing object out of the backends or get a new one for us
            if database_authenticator.id not in authentication_backends:
                try:
                    authentication_backends[database_authenticator.id] = get_authenticator_plugin(database_authenticator.type)
                except ImportError:
                    continue
            else:
                if authentication_backends[database_authenticator.id].type != database_authenticator.type:
                    try:
                        authentication_backends[database_authenticator.id] = get_authenticator_plugin(database_authenticator.type)
                    except ImportError:
                        # Since we failed to load this authenticator_plugin lets take it out of the cache
                        del authentication_backends[database_authenticator.id]
                        continue
            authenticator_object = authentication_backends[database_authenticator.id]
            authenticator_object.update_if_needed(database_authenticator)
            user = authenticator_object.authenticate(request, *args, **kwargs)
            if user:
                logger.info(f'User {user.username} logged in from {database_authenticator.name}')
                return user

        return None
