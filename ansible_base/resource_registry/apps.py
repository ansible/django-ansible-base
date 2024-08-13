import logging

from django.apps import AppConfig
from django.conf import settings
from django.db.models import TextField, signals
from django.db.models.functions import Cast
from django.db.utils import IntegrityError

import ansible_base.lib.checks  # noqa: F401 - register checks
from ansible_base.lib.utils.db import ensure_transaction

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
        for key, resource_config in registry.get_resources().items():
            content = ContentType.objects.get_for_model(resource_config.model)

            if serializer := resource_config.managed_serializer:
                resource_type = f"shared.{serializer.RESOURCE_TYPE}"
            else:
                resource_type = f"{registry.api_config.service_type}.{content.model}"
            defaults = {"externally_managed": resource_config.externally_managed, "name": resource_type}

            try:
                ResourceType.objects.update_or_create(content_type=content, defaults=defaults)
            except IntegrityError as e:
                # if previous DAB migrations used the wrong content type id, we need to correct that now
                # to eliminate integrity errors at the end of the migration process when this function
                # gets called.
                if not ResourceType.objects.filter(name=resource_type).exists():
                    raise e
                rt = ResourceType.objects.get(name=resource_type)
                logger.warn(f"changing content_type for '{resource_type}' from '{rt.content_type.model}' to '{content.model}'")
                rt.content_type = content
                for k, v in defaults.items():
                    setattr(rt, k, v)
                rt.save()

        # Create resources
        for r_type in ResourceType.objects.all():
            resource_model = apps.get_model(r_type.content_type.app_label, r_type.content_type.model)
            resource_config = registry.get_config_for_model(resource_model)

            logger.info(f"adding unmigrated resources for {r_type.name}")

            missing_resources_qs = resource_model.objects.annotate(pk_text=Cast('pk', TextField())).exclude(
                pk_text__in=Resource.objects.filter(content_type=r_type.content_type).values("object_id")
            )

            data = []
            for obj in missing_resources_qs:
                data.append(init_resource_from_object(obj, resource_model=Resource, resource_type=r_type, resource_config=resource_config))

            Resource.objects.bulk_create(data, ignore_conflicts=True)
            r_type.save()


def proxies_of_model(cls):
    """Return models that are a proxy of cls"""
    for sub_cls in cls.__subclasses__():
        if sub_cls._meta.concrete_model is cls:
            yield sub_cls


def _should_reverse_sync():
    enabled = not getattr(settings, 'DISABLE_RESOURCE_SERVER_SYNC', False)
    for setting in ('RESOURCE_SERVER', 'RESOURCE_SERVICE_PATH'):
        if not getattr(settings, setting, False):
            enabled = False
            break
    if hasattr(settings, 'RESOURCE_SERVER') and ('SECRET_KEY' not in settings.RESOURCE_SERVER or not settings.RESOURCE_SERVER['SECRET_KEY']):
        enabled = False
    return enabled


def connect_resource_signals(sender, **kwargs):
    from ansible_base.resource_registry.signals import handlers

    for model in handlers.get_resource_models():
        for cls in [model, *proxies_of_model(model)]:
            # On registration, resource registry registers the concrete model
            # so we connect signals for proxies of that model, and not the other way around
            signals.post_save.connect(handlers.update_resource, sender=cls)
            signals.post_delete.connect(handlers.remove_resource, sender=cls)

            if _should_reverse_sync():
                signals.pre_save.connect(handlers.decide_to_sync_update, sender=cls)
                signals.post_save.connect(handlers.sync_to_resource_server_post_save, sender=cls)
                signals.pre_delete.connect(handlers.sync_to_resource_server_pre_delete, sender=cls)

                # Wrap save() in a transaction and sync to resource server
                cls._original_save = cls.save

                # Avoid late binding issues
                def save(self, *args, _original_save=cls._original_save, **kwargs):
                    with ensure_transaction():
                        _original_save(self, *args, **kwargs)

                cls.save = save

                # Wrap delete() in a transaction and remove from resource server
                cls._original_delete = cls.delete

                # Avoid late binding issues
                def delete(self, *args, _original_delete=cls._original_delete, **kwargs):
                    with ensure_transaction():
                        _original_delete(self, *args, **kwargs)

                cls.delete = delete


def disconnect_resource_signals(sender, **kwargs):
    from ansible_base.resource_registry.signals import handlers

    for model in handlers.get_resource_models():
        for cls in [model, *proxies_of_model(model)]:
            signals.post_save.disconnect(handlers.update_resource, sender=cls)
            signals.post_delete.disconnect(handlers.remove_resource, sender=cls)

            signals.pre_save.disconnect(handlers.decide_to_sync_update, sender=cls)
            signals.post_save.disconnect(handlers.sync_to_resource_server_post_save, sender=cls)
            signals.pre_delete.disconnect(handlers.sync_to_resource_server_pre_delete, sender=cls)

            if hasattr(cls, '_original_save'):
                cls.save = cls._original_save
                del cls._original_save

            if hasattr(cls, '_original_delete'):
                cls.delete = cls._original_delete
                del cls._original_delete


class ResourceRegistryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base.resource_registry'
    label = 'dab_resource_registry'
    verbose_name = 'Service resources API'

    def ready(self):
        connect_resource_signals(sender=None)
        signals.pre_migrate.connect(disconnect_resource_signals, sender=self)
        signals.post_migrate.connect(initialize_resources, sender=self)
        signals.post_migrate.connect(connect_resource_signals, sender=self)
