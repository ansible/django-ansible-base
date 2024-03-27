#  Copyright 2024 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import logging

from django.conf import settings

from ansible_base.rbac.permission_registry import permission_registry

logger = logging.getLogger('ansible_base.rbac.migrations._managed_definitions')


def get_or_create_managed(name, description, ct, permissions, RoleDefinition):
    role_definition, created = RoleDefinition.objects.get_or_create(
        name=name,
        defaults={'managed': True, 'description': description, 'content_type': ct}
    )
    role_definition.permissions.set(list(permissions))

    if not role_definition.managed:
        role_definition.managed = True
        role_definition.save(update_fields=['managed'])

    if created:
        logger.info(f'Created RoleDefinition {role_definition.name} pk={role_definition} with {len(permissions)} permissions')

    return role_definition


def setup_managed_role_definitions(apps, schema_editor):
    """
    Idepotent method to create or sync the managed role definitions
    """
    to_create = settings.ANSIBLE_BASE_ROLE_PRECREATE

    ContentType = apps.get_model('contenttypes', 'ContentType')
    Permission = apps.get_model('dab_rbac', 'DABPermission')
    RoleDefinition = apps.get_model('dab_rbac', 'RoleDefinition')
    Organization = apps.get_model(settings.ANSIBLE_BASE_ORGANIZATION_MODEL)
    org_ct = ContentType.objects.get_for_model(Organization)
    managed_role_definitions = []

    org_perms = set()
    for cls in permission_registry._registry:
        ct = ContentType.objects.get_for_model(cls)
        object_perms = set(Permission.objects.filter(content_type=ct))
        # Special case for InstanceGroup which has an organiation field, but is not an organization child object
        if cls._meta.model_name != 'instancegroup':
            org_perms.update(object_perms)

        if 'object_admin' in to_create and cls != Organization:
            indiv_perms = object_perms.copy()
            add_perms = [perm for perm in indiv_perms if perm.codename.startswith('add_')]
            if add_perms:
                for perm in add_perms:
                    indiv_perms.remove(perm)

            managed_role_definitions.append(
                get_or_create_managed(
                    to_create['object_admin'].format(cls=cls),
                    f'Has all permissions to a single {cls._meta.verbose_name}',
                    ct,
                    indiv_perms,
                    RoleDefinition
                )
            )

        if 'org_children' in to_create and cls != Organization:
            org_child_perms = object_perms.copy()
            org_child_perms.add(Permission.objects.get(codename='view_organization'))

            managed_role_definitions.append(
                get_or_create_managed(
                    to_create['org_children'].format(cls=cls),
                    f'Has all permissions to {cls._meta.verbose_name_plural} within an organization',
                    org_ct,
                    org_child_perms,
                    RoleDefinition,
                )
            )

        if 'special' in to_create:
            special_perms = []
            for perm in object_perms:
                if perm.codename.split('_')[0] not in ('add', 'change', 'update', 'delete', 'view'):
                    special_perms.append(perm)
            for perm in special_perms:
                action = perm.codename.split('_')[0]
                view_perm = Permission.objects.get(content_type=ct, codename__startswith='view_')
                managed_role_definitions.append(
                    get_or_create_managed(
                        to_create['special'].format(cls=cls, action=action),
                        f'Has {action} permissions to a single {cls._meta.verbose_name}',
                        ct,
                        [perm, view_perm],
                        RoleDefinition,
                    )
                )

    if 'org_admin' in to_create:
        managed_role_definitions.append(
            get_or_create_managed(
                to_create['org_admin'].format(cls=Organization),
                'Has all permissions to a single organization and all objects inside of it',
                org_ct,
                org_perms,
                RoleDefinition,
            )
        )

    unexpected_role_definitions = RoleDefinition.objects.filter(managed=True).exclude(pk__in=[rd.pk for rd in managed_role_definitions])
    for role_definition in unexpected_role_definitions:
        logger.info(f'Deleting old managed role definition {role_definition.name}, pk={role_definition.pk}')
        role_definition.delete()
