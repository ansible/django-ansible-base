from django.apps import AppConfig
from django.db.models.signals import post_migrate

import ansible_base.checks  # noqa: F401 - register checks


def initialize_resources(sender, apps, **kwargs):
    from ansible_base.models.resource import get_registry

    Resource = apps.get_model("ansible_base", "Resource")
    ResourceType = apps.get_model("ansible_base", "ResourceType")
    ContentType = apps.get_model("contenttypes", "ContentType")

    print("updating resource types")
    registry = get_registry()
    for key, resource in registry.get_resources().items():
        content = ContentType.objects.get_for_model(resource["model"])
        resource_type = f"{registry.api_config.service_type}.{content.model}"
        defaults = {"externally_managed": resource["externally_managed"], "resource_type": resource_type}
        ResourceType.objects.update_or_create(content_type=content, defaults=defaults)

    for r_type in ResourceType.objects.filter(migrated=False):
        resource_model = apps.get_model(r_type.content_type.app_label, r_type.content_type.model)
        print(f"adding unmigrated resources for {r_type.content_type.model}")

        data = []
        for obj in resource_model.objects.all():
            resource = Resource(object_id=obj.pk, content_type=r_type.content_type)
            if hasattr(obj, "name"):
                resource.name = obj.name
            data.append(resource)

        Resource.objects.bulk_create(data, ignore_conflicts=True)
        r_type.migrated = True
        r_type.save()


class AnsibleAuthConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base'

    def ready(self):
        post_migrate.connect(initialize_resources, sender=self)

        from ansible_base.signals import handlers  # noqa: F401 - register signals
