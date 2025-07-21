from django.apps import AppConfig

from ansible_base.api_documentation.customizations import apply_authentication_customizations


class ApiDocumentationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base.api_documentation'
    label = 'dab_api_documentation'

    def ready(self):
        from django.conf import settings

        if 'ansible_base.authentication' in settings.INSTALLED_APPS:
            apply_authentication_customizations()

        # Import filter extensions to register them with drf-spectacular
        if 'ansible_base.rest_filters' in settings.INSTALLED_APPS and 'ansible_base.api_documentation' in settings.INSTALLED_APPS:
            # If this service is using DAB rest filters and api documentation, load our filter extensions for OpenAPI
            from ansible_base.api_documentation import filter_extensions  # noqa: F401
