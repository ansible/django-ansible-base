import logging
from collections import OrderedDict
from typing import Any

from django.db.models import Count, Max

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugin

logger = logging.getLogger("ansible_base.authentication.authenticator_cache")


class IncompleteAuthenticatorPluginLoad(Exception):
    """Carry usable plugins when one or more enabled authenticators could not initialize."""

    def __init__(self, plugins: OrderedDict[int, Any]) -> None:
        """Retain successfully initialized plugins without allowing them to be cached."""
        self.plugins = plugins


def get_authenticator_cache_version(authenticators) -> tuple[Any, int]:
    """Return a shared-database version that changes for authenticator edits and deletions."""
    version = authenticators.aggregate(last_modified=Max("modified"), count=Count("id"))
    return version["last_modified"], version["count"]


def load_authenticator_plugins(authenticators) -> OrderedDict[int, Any]:
    """Instantiate available plugins and bind each to its database authenticator.

    An initialization failure must not prevent healthy authenticators from
    serving a request. Raise ``IncompleteAuthenticatorPluginLoad`` after
    processing all rows so callers can use the healthy subset without caching
    it; a later request then retries the failed authenticator.
    """
    authentication_backends = OrderedDict()
    incomplete = False

    for database_authenticator in authenticators:
        try:
            plugin = get_authenticator_plugin(database_authenticator.type)
            plugin.update_if_needed(database_authenticator)
        except Exception:
            logger.exception(
                'Unable to initialize authenticator type "%s" with ID "%s"',
                database_authenticator.type,
                database_authenticator.id,
            )
            incomplete = True
            continue

        authentication_backends[database_authenticator.id] = plugin

    if incomplete:
        raise IncompleteAuthenticatorPluginLoad(authentication_backends)

    return authentication_backends
