import logging

from django.apps import apps as global_apps
from django.conf import settings
from django.contrib.contenttypes.management import create_contenttypes
from django.db import DEFAULT_DB_ALIAS, models, router

from ansible_base.rbac import permission_registry

logger = logging.getLogger("ansible_base.rbac.migrations._utils")


def create_custom_permissions(app_config, verbosity=2, interactive=True, using=DEFAULT_DB_ALIAS, apps=global_apps, **kwargs):
    """
    This is modified from the django auth.
    Use this to create permissions in specified settings.ANSIBLE_BASE_PERMISSION_MODEL
    this will only create permissions for registered models
    """
    if not app_config.models_module:
        return

    # Ensure that contenttypes are created for this app. Needed if
    # 'django.contrib.auth' is in INSTALLED_APPS before
    # 'django.contrib.contenttypes'.
    create_contenttypes(
        app_config,
        verbosity=verbosity,
        interactive=interactive,
        using=using,
        apps=apps,
        **kwargs,
    )

    app_label = app_config.label
    try:
        app_config = apps.get_app_config(app_label)
        ContentType = apps.get_model("contenttypes", "ContentType")
        Permission = apps.get_model(settings.ANSIBLE_BASE_PERMISSION_MODEL)
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
        ctype = ContentType.objects.db_manager(using).get_for_model(
            klass, for_concrete_model=False
        )

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
    all_perms = set(
        Permission.objects.using(using)
        .filter(content_type__in=ctypes)
        .values_list("content_type", "codename")
    )

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


def give_permissions(apps, rd, users=(), teams=(), object_id=None, content_type_id=None):
    """
    Give user permission to an object, but for use in migrations
    rd - role definition to grant the user
    users - list of users to give this permission to
    teams - list of teams to give this permission to, can be objects or id list

    target object is implicitly specified by
    object_id - primary key of the object permission will apply to
    content_type_id - primary key of the content type for the object
    """
    ObjectRole = apps.get_model('dab_rbac', 'ObjectRole')

    # Create the object role and add users to it
    object_role_fields = dict(role_definition=rd, object_id=object_id, content_type_id=content_type_id)
    object_role, _ = ObjectRole.objects.get_or_create(**object_role_fields)

    if users:
        # Django seems to not process through_fields correctly in migrations
        # so it will use created_by as the target field name, which is incorrect, should be user
        # basically can not use object_role.users.add(actor)
        RoleUserAssignment = apps.get_model('dab_rbac', 'RoleUserAssignment')
        user_assignments = [
            RoleUserAssignment(object_role=object_role, user=user, **object_role_fields)
            for user in users
        ]
        RoleUserAssignment.objects.bulk_create(user_assignments)
    if teams:
        RoleTeamAssignment = apps.get_model('dab_rbac', 'RoleTeamAssignment')
        # AWX has trouble getting the team object, conditionally accept team id list
        if isinstance(teams[0], models.Model):
            team_assignments = [
                RoleTeamAssignment(object_role=object_role, team=team, **object_role_fields)
                for team in teams
            ]
        else:
            team_assignments = [
                RoleTeamAssignment(object_role=object_role, team_id=team_id, **object_role_fields)
                for team_id in teams
            ]
        RoleTeamAssignment.objects.bulk_create(team_assignments)
