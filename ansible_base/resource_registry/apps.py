import logging

from django.apps import AppConfig
from django.apps import apps as django_apps
from django.conf import settings
from django.db.models import Case, Exists, OuterRef, TextField, UUIDField, Value, When, signals
from django.db.models.functions import Cast
from django.db.utils import IntegrityError

import ansible_base.lib.checks  # noqa: F401 - register checks
from ansible_base.lib.utils.db import ensure_transaction, migrations_are_complete
from ansible_base.resource_registry.utils.settings import resource_server_defined

logger = logging.getLogger("ansible_base.resource_registry.apps")


def _sync_assignment_resource_ids(sender, instance, created, update_fields, **kwargs):
    if not created:
        if update_fields is not None and 'ansible_id' not in update_fields:
            return
        if update_fields is None and getattr(instance, '_loaded_ansible_id', instance.ansible_id) == instance.ansible_id:
            return

    _update_assignment_resource_ids(instance.content_type, {str(instance.object_id): instance.ansible_id})
    instance._loaded_ansible_id = instance.ansible_id


def _update_assignment_resource_ids(content_type, resource_ids):
    if not django_apps.is_installed('ansible_base.rbac') or not resource_ids:
        return

    from ansible_base.rbac.models import DABContentType, RoleTeamAssignment, RoleUserAssignment
    from ansible_base.rbac.remote import get_local_resource_services

    content_types = DABContentType.objects.filter(
        service__in=get_local_resource_services(),
        app_label=content_type.app_label,
        model=content_type.model,
    )
    object_id_case = Case(
        *(When(object_id=object_id, then=Value(ansible_id)) for object_id, ansible_id in resource_ids.items()),
        output_field=UUIDField(),
    )
    for assignment_model in (RoleUserAssignment, RoleTeamAssignment):
        assignment_model.objects.filter(content_type__in=content_types, object_id__in=resource_ids).update(object_ansible_id=object_id_case)


def _sync_backfilled_resource_ids(resource_cls, content_type, object_ids):
    if not object_ids:
        return
    resource_ids = dict(resource_cls.objects.filter(content_type=content_type, object_id__in=object_ids).values_list('object_id', 'ansible_id'))
    _update_assignment_resource_ids(content_type, resource_ids)


def _sync_resource_types(registry, resource_type_cls, content_type_cls):
    """Create or update ResourceType rows for every resource in the registry."""
    for key, resource_config in registry.get_resources().items():
        content = content_type_cls.objects.get_for_model(resource_config.model)

        if serializer := resource_config.managed_serializer:
            resource_type = f"shared.{serializer.RESOURCE_TYPE}"
        else:
            resource_type = f"{registry.api_config.service_type}.{content.model}"
        defaults = {
            "externally_managed": resource_config.externally_managed,
            "name": resource_type,
        }

        try:
            resource_type_cls.objects.update_or_create(content_type=content, defaults=defaults)
        except IntegrityError as e:
            # if previous DAB migrations used the wrong content type id, we need to correct that now
            # to eliminate integrity errors at the end of the migration process when this function
            # gets called.
            if not resource_type_cls.objects.filter(name=resource_type).exists():
                raise e
            rt = resource_type_cls.objects.get(name=resource_type)
            logger.warn(f"changing content_type for '{resource_type}' from '{rt.content_type.model}' to '{content.model}'")
            # Remove any stale row that already owns the target content_type,
            # otherwise the OneToOne unique constraint prevents reassignment.
            stale = resource_type_cls.objects.filter(content_type=content).exclude(pk=rt.pk)
            if stale.exists():
                logger.warn(f"deleting stale ResourceType row(s) that own content_type '{content.model}'")
                stale.delete()
            rt.content_type = content
            for k, v in defaults.items():
                setattr(rt, k, v)
            rt.save()


def _backfill_missing_resources(registry, resource_cls, resource_type_cls, apps):
    """Create Resource rows for model instances that lack one."""
    from ansible_base.resource_registry.models import init_resource_from_object

    for r_type in resource_type_cls.objects.all():
        resource_model = apps.get_model(r_type.content_type.app_label, r_type.content_type.model)
        resource_config = registry.get_config_for_model(resource_model)

        logger.info(f"adding unmigrated resources for {r_type.name}")

        missing_resources_qs = resource_model.objects.annotate(pk_text=Cast("pk", TextField())).exclude(
            Exists(resource_cls.objects.filter(content_type=r_type.content_type, object_id=OuterRef("pk_text")))
        )

        batch_size = 1000
        data = []
        for obj in missing_resources_qs.iterator(chunk_size=batch_size):
            data.append(
                init_resource_from_object(
                    obj,
                    resource_model=resource_cls,
                    resource_type=r_type,
                    resource_config=resource_config,
                )
            )
            if len(data) == batch_size:
                resource_cls.objects.bulk_create(data, ignore_conflicts=True)
                _sync_backfilled_resource_ids(resource_cls, r_type.content_type, [resource.object_id for resource in data])
                data.clear()
        if data:
            resource_cls.objects.bulk_create(data, ignore_conflicts=True)
            _sync_backfilled_resource_ids(resource_cls, r_type.content_type, [resource.object_id for resource in data])
        r_type.save()


def initialize_resources(sender, force=False, **kwargs):
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

    if not force and not migrations_are_complete():
        logger.info("Not running resource_registry post_migrate because migrations are incomplete")
        return

    apps = kwargs.get("apps")
    if apps is None:
        from django.apps import apps

    Resource = apps.get_model("dab_resource_registry", "Resource")
    ResourceType = apps.get_model("dab_resource_registry", "ResourceType")
    ContentType = apps.get_model("contenttypes", "ContentType")

    logger.info("updating resource types")
    registry = get_registry()
    if registry:
        _sync_resource_types(registry, ResourceType, ContentType)

        # Skip the expensive missing-resource scan when no migrations were applied.
        # ResourceType creation above must still run because post_save signal
        # handlers depend on ResourceType records existing.
        plan = kwargs.get("plan", None)
        if plan is not None and len(plan) == 0:
            logger.info("Skipping missing-resource scan — no migrations were applied")
            return

        _backfill_missing_resources(registry, Resource, ResourceType, apps)


def proxies_of_model(cls):
    """Return models that are a proxy of cls"""
    for sub_cls in cls.__subclasses__():
        if sub_cls._meta.concrete_model is cls:
            yield sub_cls


def _should_reverse_sync():
    enabled = getattr(settings, "RESOURCE_SERVER_SYNC_ENABLED", False)
    if enabled and (not resource_server_defined()):
        logger.debug("RESOURCE_SERVER is not configured. Reverse sync will not be enabled.")
        enabled = False
    if enabled and resource_server_defined() and ("SECRET_KEY" not in settings.RESOURCE_SERVER or not settings.RESOURCE_SERVER["SECRET_KEY"]):
        logger.error("RESOURCE_SERVER['SECRET_KEY'] is not configured. Reverse sync will not be enabled.")
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

            if hasattr(cls, "_original_save"):
                cls.save = cls._original_save
                del cls._original_save

            if hasattr(cls, "_original_delete"):
                cls.delete = cls._original_delete
                del cls._original_delete


class ResourceRegistryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ansible_base.resource_registry"
    label = "dab_resource_registry"
    verbose_name = "Service resources API"

    def ready(self):
        from django.apps import apps

        if apps.is_installed('ansible_base.rbac'):
            from ansible_base.resource_registry.models import Resource

            signals.post_save.connect(_sync_assignment_resource_ids, sender=Resource, dispatch_uid='sync_assignment_resource_ids')

        connect_resource_signals(sender=None)
        signals.pre_migrate.connect(disconnect_resource_signals, sender=self)
        signals.post_migrate.connect(initialize_resources, sender=self)
        signals.post_migrate.connect(connect_resource_signals, sender=self)
