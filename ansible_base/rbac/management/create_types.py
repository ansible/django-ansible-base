import logging
from typing import Type

from django.apps import apps as global_apps
from django.db import DEFAULT_DB_ALIAS, connection, models

from ansible_base.rbac import permission_registry
from ansible_base.rbac.remote import (
    RemoteObject,
    get_local_resource_services,
    get_remote_standin_class,
    get_resource_prefix,
)

logger = logging.getLogger(__name__)


def get_local_dab_contenttypes(using: str, ct_model: Type[models.Model]) -> dict[tuple[str, str], models.Model]:
    # This should work in migration scenarios, but other code checks for existence of it on manager
    ct_model.objects.clear_cache()

    return {(ct.service, ct.model): ct for ct in ct_model.objects.using(using)}


def model_class(apps, ct):
    "Model methods normally can not be used in migrations so this is a safer utility method"
    if ct.service not in get_local_resource_services():
        return get_remote_standin_class(ct)

    return apps.get_model(ct.app_label, ct.model)


def create_DAB_contenttypes(
    verbosity=2,
    using=DEFAULT_DB_ALIAS,
    apps=global_apps,
) -> list:
    """Create DABContentType for models in the given app.

    This is significantly different from the ContentType post-migrate method,
    because that creates types for all apps, and so this is only called one app at a time.
    DAB RBAC runs its post_migration logic just once, because the model list
    comes from the permission registry.

    Returns a list of the _new_ content types created
    """
    dab_ct_cls = apps.get_model("dab_rbac", "DABContentType")
    ct_cls = apps.get_model("contenttypes", "ContentType")

    content_types = get_local_dab_contenttypes(using, dab_ct_cls)

    ct_data = []
    for model in permission_registry.all_registered_models:
        service = get_resource_prefix(model)
        if (service, model._meta.model_name) not in content_types:
            # The content type is not seen in existing entries, add to list for creation
            ct_item_data = {
                'service': service,
                'app_label': model._meta.app_label,
                'model': model._meta.model_name,
                'api_slug': f'{service}.{model._meta.model_name}',
                'pk_field_type': model._meta.pk.db_type(connection),
            }
            # To make usage earier in a transitional period, we will set the content type
            # of any new entries created here to the id of its corresponding ContentType
            # from the actual contenttypes app, allowing many filters to work
            real_ct = ct_cls.objects.get_for_model(model)
            if not dab_ct_cls.objects.filter(id=real_ct.id).exists():
                ct_item_data['id'] = real_ct.id
            else:
                current_max_id = dab_ct_cls.objects.order_by('-id').values_list('id', flat=True).first() or 0
                ct_item_data['id'] = current_max_id + 1
            ct_data.append(ct_item_data)

    # Create the items here
    cts = []
    for ct_item_data in ct_data:
        cts.append(dab_ct_cls.objects.create(**ct_item_data))

    if verbosity >= 2:
        for ct in cts:
            logger.debug("Adding DAB content type " f"'{ct.service}:{ct.app_label} | {ct.model}'")

    # Update, or set for the first time, the parent type reference
    updated_ct = 0
    for ct in dab_ct_cls.objects.all():
        try:
            ct_model_class = model_class(apps, ct)
        except LookupError:
            logger.warning(f'Model {ct.model} is in the permission_registry but not in the current app state. ' 'This could be okay in reverse migrations.')
            continue
        if issubclass(ct_model_class, RemoteObject):
            continue  # remote types not managed here
        if not permission_registry.is_registered(ct_model_class):
            logger.warning(f'{ct.model} is a stale content type in DAB RBAC')
            continue
        if parent_model := permission_registry.get_parent_model(ct_model_class):
            parent_content_type = dab_ct_cls.objects.get_for_model(parent_model)
            if ct.parent_content_type != parent_content_type:
                ct.parent_content_type = parent_content_type
                ct.save(update_fields=['parent_content_type'])
                updated_ct += 1
    if updated_ct:
        # If this happens outside of the migration when the entries were created, that would be notable
        logger.info(f'Updated the parent reference of {updated_ct} content types')

    return cts
