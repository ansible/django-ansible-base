import logging

from django.apps import AppConfig
from django.db.models.signals import post_migrate

import ansible_base.lib.checks  # noqa: F401 - register checks

logger = logging.getLogger('ansible_base.resource_registry.apps')


def initialize_resources(sender, apps, **kwargs):
    from ansible_base.resource_registry.registry import get_registry

    Resource = apps.get_model("dab_resource_registry", "Resource")
    ResourceType = apps.get_model("dab_resource_registry", "ResourceType")
    ContentType = apps.get_model("contenttypes", "ContentType")

    logger.info("updating resource types")
    registry = get_registry()
    if registry:
        # Create resource types
        for key, resource in registry.get_resources().items():
            content = ContentType.objects.get_for_model(resource.model)

            if serializer := resource.managed_serializer:
                resource_type = f"shared.{serializer.RESOURCE_TYPE}"
            else:
                resource_type = f"{registry.api_config.service_type}.{content.model}"
            defaults = {"externally_managed": resource.externally_managed, "name": resource_type}
            ResourceType.objects.update_or_create(content_type=content, defaults=defaults)

        # Create resources
        for r_type in ResourceType.objects.filter(migrated=False):
            resource_model = apps.get_model(r_type.content_type.app_label, r_type.content_type.model)

            logger.info(f"adding unmigrated resources for {r_type.name}")

            data = []
            for obj in resource_model.objects.all():
                data.append(Resource.init_from_object(obj, resource_type=r_type))

            Resource.objects.bulk_create(data, ignore_conflicts=True)
            r_type.migrated = True
            r_type.save()


class AnsibleAuthConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base.resource_registry'
    label = 'dab_resource_registry'
    verbose_name = 'Service resources API'

    def ready(self):
        post_migrate.connect(initialize_resources, sender=self)

        from ansible_base.resource_registry.signals import handlers  # noqa: F401 - register signals
