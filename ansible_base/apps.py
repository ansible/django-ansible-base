from django.apps import AppConfig

import ansible_base.checks  # noqa: F401 - register checks
from ansible_base.rbac.permission_registry import permission_registry


class AnsibleAuthConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base'

    def ready(self):
        permission_registry.call_when_apps_ready(self.apps)
