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

import time
from os import environ

from crum import impersonate
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from ansible_base.authentication.models import Authenticator, AuthenticatorUser
from ansible_base.rbac.models import RoleDefinition
from ansible_base.rbac.validators import combine_values, permissions_allowed_for_role
from test_app.models import EncryptionModel, InstanceGroup, Inventory, Organization, Team, User


class Command(BaseCommand):
    help = 'Creates demo data for development.'

    def create_large(self, data_counts):
        "Data is not made with bulk_create at the moment to work to the resource of dab_resource_registry"
        start = time.time()
        self.stdout.write('')
        self.stdout.write('About to create large demo data set. This will take a while.')
        for cls in (Organization, Team, User):
            count = data_counts[cls._meta.model_name]
            for i in range(count):
                name = f'large_{cls._meta.model_name}_{i}'
                data = {'name': name}
                if cls is User:
                    data = {'username': name}
                elif cls is Team:
                    data['organization_id'] = i + 1  # fudged, teams fewer than orgs
                cls.objects.create(**data)
            self.stdout.write(f'Created {count} {cls._meta.model_name}')
        self.stdout.write(f'Finished creating large demo data in {time.time() - start:.2f} seconds')

    def handle(self, *args, **kwargs):
        (awx, _) = Organization.objects.get_or_create(name='AWX_community')
        (galaxy, _) = Organization.objects.get_or_create(name='Galaxy_community')

        (spud, _) = User.objects.get_or_create(username='angry_spud')
        (bull_bot, _) = User.objects.get_or_create(username='ansibullbot')
        (admin, _) = User.objects.get_or_create(username='admin')
        admin.is_staff = True
        admin.is_superuser = True
        admin_password = environ.get('DJANGO_SUPERUSER_PASSWORD', 'admin')
        admin.set_password(admin_password)
        admin.save()
        spud.set_password('password')
        spud.save()
        with impersonate(spud):
            Team.objects.get_or_create(name='awx_docs', defaults={'organization': awx})
            awx_devs, _ = Team.objects.get_or_create(name='awx_devs', defaults={'organization': awx})
            EncryptionModel.objects.get_or_create(
                name='foo', defaults={'testing1': 'should not show this value!!', 'testing2': 'this value should also not be shown!'}
            )
            operator_stuff, _ = Organization.objects.get_or_create(name='Operator_community')
            (db_authenticator, _) = Authenticator.objects.get_or_create(
                name='Local Database Authenticator',
                defaults={
                    'enabled': True,
                    'create_objects': True,
                    'configuration': {},
                    'remove_users': False,
                    'type': 'ansible_base.authentication.authenticator_plugins.local',
                },
            )
            AuthenticatorUser.objects.get_or_create(
                uid=admin.username,
                defaults={
                    'user': admin,
                    'provider': db_authenticator,
                },
            )

            # Inventory objects exist inside of an organization
            Inventory.objects.create(name='K8S clusters', organization=operator_stuff)
            Inventory.objects.create(name='Galaxy Host', organization=galaxy)
            Inventory.objects.create(name='AWX deployment', organization=awx)
            # Objects that have no associated organization
            InstanceGroup.objects.create(name='Default')
            isolated_group = InstanceGroup.objects.create(name='Isolated Network')

        with impersonate(bull_bot):
            Team.objects.get_or_create(name='community.general maintainers', defaults={'organization': galaxy})

        # NOTE: managed role definitions are turned off, you could turn them on and get rid of these
        org_perms = combine_values(permissions_allowed_for_role(Organization))
        org_admin, _ = RoleDefinition.objects.get_or_create(
            name='Organization admin permissions',
            permissions=org_perms,
            defaults={'content_type': ContentType.objects.get_for_model(Organization), 'managed': True},
        )
        ig_admin, _ = RoleDefinition.objects.get_or_create(
            name='AWX InstanceGroup admin',
            permissions=['change_instancegroup', 'delete_instancegroup', 'view_instancegroup'],
            defaults={'content_type': ContentType.objects.get_for_model(InstanceGroup)},
        )
        team_member, _ = RoleDefinition.objects.get_or_create(
            name='Special Team member role',
            permissions=['view_team', 'member_team'],
            defaults={'content_type': ContentType.objects.get_for_model(Team), 'managed': True},
        )

        org_admin_user, _ = User.objects.get_or_create(username='org_admin')
        ig_admin_user, _ = User.objects.get_or_create(username='instance_group_admin')
        org_admin.give_permission(org_admin_user, awx)
        ig_admin.give_permission(ig_admin_user, isolated_group)
        for user in (org_admin_user, ig_admin_user, spud):
            user.set_password('password')
            user.save()

        team_member.give_permission(spud, awx_devs)

        self.stdout.write('Finished creating demo data!')
        self.stdout.write(f'Admin user password: {admin_password}')

        if environ.get('LARGE') and not Organization.objects.filter(name__startswith='large').exists():
            self.create_large(settings.DEMO_DATA_COUNTS)
