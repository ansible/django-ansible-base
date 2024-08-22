from django.db import models

# This method has moved, and this is put here temporarily to make branch management easier
from ansible_base.rbac.management import create_dab_permissions as create_custom_permissions  # noqa


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
        RoleUserAssignment.objects.bulk_create(user_assignments, ignore_conflicts=True)
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
        RoleTeamAssignment.objects.bulk_create(team_assignments, ignore_conflicts=True)
