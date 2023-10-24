from django.apps import AppConfig

import ansible_base.checks  # noqa: F401 - register checks


class AnsibleAuthConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base'
