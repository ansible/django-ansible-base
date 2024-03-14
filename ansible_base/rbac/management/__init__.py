import logging

from django.apps import apps as global_apps
from django.contrib.contenttypes.management import create_contenttypes
from django.db import DEFAULT_DB_ALIAS, router

from ansible_base.rbac import permission_registry

logger = logging.getLogger(__name__)


def create_dab_permissions(app_config, verbosity=2, interactive=True, using=DEFAULT_DB_ALIAS, apps=global_apps, **kwargs):
    """
    This is modified from the django auth.
    This will create DABPermission entries
    this will only create permissions for registered models
    """
    if not getattr(app_config, 'models_module', None):
        return

    # exit early if nothing is registered for this app
    app_label = app_config.label
    if not any(cls._meta.app_label == app_label for cls in permission_registry._registry):
        return

    # Ensure that contenttypes are created for this app. Needed if
    # 'ansible_base.rbac' is in INSTALLED_APPS before
    # 'django.contrib.contenttypes'.
    create_contenttypes(
        app_config,
        verbosity=verbosity,
        interactive=interactive,
        using=using,
        apps=apps,
        **kwargs,
    )

    try:
        app_config = apps.get_app_config(app_label)
        ContentType = apps.get_model("contenttypes", "ContentType")
        Permission = apps.get_model("dab_rbac", "DABPermission")
    except LookupError:
        return

    if not router.allow_migrate_model(using, Permission):
        return

    # This will hold the permissions we're looking for as (content_type, (codename, name))
    searched_perms = []
    # The codenames and ctypes that should exist.
    ctypes = set()
    for klass in app_config.get_models():
        if not permission_registry.is_registered(klass):
            continue
        # Force looking up the content types in the current database
        # before creating foreign keys to them.
        ctype = ContentType.objects.db_manager(using).get_for_model(klass, for_concrete_model=False)

        ctypes.add(ctype)

        for action in klass._meta.default_permissions:
            searched_perms.append(
                (
                    ctype,
                    (
                        f"{action}_{klass._meta.model_name}",
                        f"Can {action} {klass._meta.verbose_name_raw}",
                    ),
                )
            )
        for codename, name in klass._meta.permissions:
            searched_perms.append((ctype, (codename, name)))

    # Find all the Permissions that have a content_type for a model we're
    # looking for.  We don't need to check for codenames since we already have
    # a list of the ones we're going to create.
    all_perms = set(Permission.objects.using(using).filter(content_type__in=ctypes).values_list("content_type", "codename"))

    perms = []
    for ct, (codename, name) in searched_perms:
        if (ct.pk, codename) not in all_perms:
            permission = Permission()
            permission._state.db = using
            permission.codename = codename
            permission.name = name
            permission.content_type = ct
            perms.append(permission)

    Permission.objects.using(using).bulk_create(perms)
    for perm in perms:
        logger.debug("Adding permission '%s'" % perm)
