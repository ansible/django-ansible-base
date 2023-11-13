from django.apps import AppConfig

import ansible_base.checks  # noqa: F401 - register checks


class AnsibleAuthConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base'

    def ready(self):
        from ansible_base.models import ResourceType, Resource, Permission

        # from ansible_base.utils.resource_registry import ResourceRegistry

        ResourceType.update_resource_types_from_registry()
        Resource.update_index()
        Permission.update_permissions()

        # Load the signals
        # import aap_gateway_api.signals  # noqa 401
