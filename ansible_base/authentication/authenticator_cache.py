from collections import OrderedDict
from typing import Any

from django.db.models import Count, Max

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugin


def get_authenticator_cache_version(authenticators) -> tuple[Any, int]:
    """Return a shared-database version that changes for authenticator edits and deletions."""
    version = authenticators.aggregate(last_modified=Max("modified"), count=Count("id"))
    return version["last_modified"], version["count"]


def load_authenticator_plugins(authenticators) -> OrderedDict[int, Any]:
    """Instantiate available plugins and bind each to its database authenticator."""
    authentication_backends = OrderedDict()

    for database_authenticator in authenticators:
        try:
            plugin = get_authenticator_plugin(database_authenticator.type)
        except ImportError:
            continue

        plugin.update_if_needed(database_authenticator)
        authentication_backends[database_authenticator.id] = plugin

    return authentication_backends
