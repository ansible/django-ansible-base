import logging

from django.apps import AppConfig
from django.db.models import signals

import ansible_base.lib.checks  # noqa: F401 - register checks

logger = logging.getLogger('ansible_base.resource_registry.apps')


def initialize_resources(sender, **kwargs):
    from ansible_base.resource_registry.registry import get_registry

    # There isn't any evidence of this in the documentation, but it appears as though
    # Django doesn't always send the "apps" arg when it dispatches the post migrate signal
    # (https://github.com/django/django/blob/stable/4.2.x/django/core/management/sql.py#L52)
    # This seems to be the case when it is called via `django-admin flush` as well as in
    # tests that use the @pytest.mark.django_db(transaction=True) decorator.
    #
    # Since the documentation doesn't provide any clues for what do to here, we've opted
    # to rescue from scenarios where "apps" is missing by just importing the "apps" module
    # directly (which is not advised to do by the django documentation for post migrate signals
    # https://docs.djangoproject.com/en/5.0/ref/signals/#post-migrate).
    #
    # While handling this for tests doesn't matter, ignoring this function when
    # `django-admin flush` is called seems like a bad idea, since that will prevent the
    # resource types from being initialized in the database, so a direct import appears to be
    # better than doing nothing.

    apps = kwargs.get("apps")
    if apps is None:
        from django.apps import apps

    from ansible_base.resource_registry.models import init_resource_from_object

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
            resource_config = registry.get_config_for_model(resource_model)

            logger.info(f"adding unmigrated resources for {r_type.name}")

            data = []
            for obj in resource_model.objects.all():
                data.append(init_resource_from_object(obj, resource_model=Resource, resource_type=r_type, resource_config=resource_config))

            Resource.objects.bulk_create(data, ignore_conflicts=True)
            r_type.migrated = True
            r_type.save()


class ResourceRegistryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base.resource_registry'
    label = 'dab_resource_registry'
    verbose_name = 'Service resources API'

    def ready(self):
        from ansible_base.resource_registry.signals import handlers

        signals.post_save.connect(handlers.update_resource)
        signals.post_delete.connect(handlers.remove_resource)
        signals.post_migrate.connect(initialize_resources, sender=self)
