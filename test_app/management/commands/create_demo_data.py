import time
from os import environ

from crum import impersonate
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ansible_base.authentication.models import Authenticator, AuthenticatorUser
from ansible_base.oauth2_provider.models import OAuth2Application
from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import DABContentType, DABPermission, RoleDefinition
from ansible_base.rbac.pipeline import bulk_give_permissions
from test_app.models import Credential, EncryptionModel, InstanceGroup, Inventory, Organization, Team, User


class Command(BaseCommand):
    help = 'Creates demo data for development.'

    def create_large(self, data_counts):
        "Data is not made with bulk_create at the moment to work to the resource of dab_resource_registry"
        start = time.time()
        self.stdout.write('')
        self.stdout.write('About to create large demo data set. This will take a while.')

        # Create standard models first
        created_org_ids = []
        for cls in (Organization, Team, User):
            count = data_counts[cls._meta.model_name]
            for i in range(count):
                name = f'large_{cls._meta.model_name}_{i}'
                data = {'name': name}
                if cls is User:
                    data = {'username': name}
                elif cls is Team:
                    # Use actual created organization IDs, cycling through them
                    if created_org_ids:
                        data['organization_id'] = created_org_ids[i % len(created_org_ids)]
                    else:
                        raise ValueError("Teams cannot be created before organizations")
                obj = cls.objects.create(**data)
                # Collect organization IDs for team creation
                if cls is Organization:
                    created_org_ids.append(obj.id)
            self.stdout.write(f'Created {count} {cls._meta.model_name}')

        # Broader resource types (AAP-88875): child objects to exercise more than just
        # orgs/teams/users on downstream query-count-scale endpoint coverage.
        created_resource_ids: dict[str, list[int]] = {}
        for cls in (Inventory, Credential):
            model_name = cls._meta.model_name
            count = data_counts.get(model_name, 0)
            ids = []
            for i in range(count):
                org_id = created_org_ids[i % len(created_org_ids)] if created_org_ids else None
                obj = cls.objects.create(name=f'large_{model_name}_{i}', organization_id=org_id)
                ids.append(obj.id)
            created_resource_ids[model_name] = ids
            if count:
                self.stdout.write(f'Created {count} {model_name}')

        # Create RoleDefinitions with permissions
        if 'roledefinition' in data_counts:
            rd_count = data_counts['roledefinition']
            org_ct = DABContentType.objects.get_for_model(Organization)

            for i in range(rd_count):
                # Create some sample permissions for each role definition
                perm1 = DABPermission.objects.create(name=f'Can view large role {i}', codename=f'view_large_role_{i}', content_type=org_ct)
                perm2 = DABPermission.objects.create(name=f'Can edit large role {i}', codename=f'edit_large_role_{i}', content_type=org_ct)

                # Create role definition with Organization content type
                rd = RoleDefinition.objects.create(name=f'Large Role Definition {i}', description=f'Large demo role definition {i}', content_type=org_ct)

                # Add permissions to the role definition
                rd.permissions.add(perm1, perm2)

            self.stdout.write(f'Created {rd_count} role definitions with permissions')

        # Permission assignments (AAP-88875): built with a single bulk_give_permissions()
        # call instead of the old nested-loop of individual give_permission() calls. Each
        # give_permission() call does its own validation/resolution/recomputation pass, so
        # at thousands of assignments the per-call path is far too slow to hit the ~1 minute
        # seeding budget; bulk_give_permissions() does that work once for the whole batch.
        #
        # Assignment diversity mirrors real customer RBAC layouts (per Alan Rominger's
        # guidance on AAP-88875):
        #   - direct object-level: user -> a specific Inventory/Credential
        #   - org-level: user -> Organization (org_admin), inherited by everything in it
        #   - team-mediated: team -> object/org, user -> team (team_member), inherited via
        #     the team
        #   - mixed: the same user index is cycled through all of the above, so a
        #     meaningful subset of users end up with direct + org-level + team-mediated
        #     permissions simultaneously
        if created_org_ids and 'user' in data_counts and 'team' in data_counts:
            large_users = list(User.objects.filter(username__startswith='large_user_'))
            large_teams = list(Team.objects.filter(name__startswith='large_team_'))
            large_orgs = list(Organization.objects.filter(id__in=created_org_ids))
            large_rds = list(RoleDefinition.objects.filter(name__startswith='Large Role Definition'))
            large_inventories = list(Inventory.objects.filter(id__in=created_resource_ids.get('inventory', [])))
            large_credentials = list(Credential.objects.filter(id__in=created_resource_ids.get('credential', [])))

            large_inv_rd, _ = RoleDefinition.objects.get_or_create(
                name='Large Inventory Admin',
                permissions=['change_inventory', 'view_inventory'],
                defaults={'content_type': permission_registry.content_type_model.objects.get_for_model(Inventory)},
            )
            large_cred_rd, _ = RoleDefinition.objects.get_or_create(
                name='Large Credential Admin',
                permissions=['use_credential', 'view_credential'],
                defaults={'content_type': permission_registry.content_type_model.objects.get_for_model(Credential)},
            )
            org_admin_rd = RoleDefinition.objects.managed.org_admin
            team_member_rd = RoleDefinition.objects.managed.team_member

            user_permissions = []
            team_permissions = []

            if large_rds and large_orgs:
                for i, user in enumerate(large_users):
                    # direct object-level
                    if large_inventories:
                        user_permissions.append((large_inv_rd, user, large_inventories[i % len(large_inventories)]))
                    if large_credentials:
                        user_permissions.append((large_cred_rd, user, large_credentials[i % len(large_credentials)]))
                    # org-level
                    user_permissions.append((org_admin_rd, user, large_orgs[i % len(large_orgs)]))
                    # a second, custom org-scoped role, on a different org, for extra diversity
                    user_permissions.append((large_rds[i % len(large_rds)], user, large_orgs[(i + 1) % len(large_orgs)]))

            if large_teams:
                for i, team in enumerate(large_teams):
                    # team-mediated: give the team its own direct/org-scoped roles
                    if large_inventories:
                        team_permissions.append((large_inv_rd, team, large_inventories[(i + 1) % len(large_inventories)]))
                    if large_credentials:
                        team_permissions.append((large_cred_rd, team, large_credentials[(i + 1) % len(large_credentials)]))
                    if large_rds and large_orgs:
                        team_permissions.append((large_rds[i % len(large_rds)], team, large_orgs[i % len(large_orgs)]))

                for i, user in enumerate(large_users):
                    # ...then put every user on a team, so they inherit the team's roles
                    # too, on top of their direct/org-level assignments above ("mixed").
                    user_permissions.append((team_member_rd, user, large_teams[i % len(large_teams)]))

            assignments = bulk_give_permissions(user_permissions=user_permissions, team_permissions=team_permissions, fire_signals_on_create=False)
            self.stdout.write(
                f'Assigned {len(user_permissions)} user-facing and {len(team_permissions)} team-facing permission '
                f'triples ({len(assignments)} assignments created) via bulk_give_permissions'
            )

        self.stdout.write(f'Finished creating large demo data in {time.time() - start:.2f} seconds')

    def handle(self, *args, **kwargs):
        try:
            admin = User.objects.get(username='admin')
        except User.DoesNotExist:
            raise CommandError('Must create admin user before create_demo_data')
        (awx, _) = Organization.objects.get_or_create(name='AWX_community')
        (galaxy, _) = Organization.objects.get_or_create(name='Galaxy_community')

        (spud, _) = User.objects.get_or_create(username='angry_spud')
        (team_member, _) = User.objects.get_or_create(username='team_member')
        (bull_bot, _) = User.objects.get_or_create(username='ansibullbot')
        (admin, _) = User.objects.get_or_create(username='admin')
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
            galaxy_inv = Inventory.objects.create(name='Galaxy Host', organization=galaxy)
            awx_inv = Inventory.objects.create(name='AWX deployment', organization=awx)
            # Objects that have no associated organization
            InstanceGroup.objects.create(name='Default')
            isolated_group = InstanceGroup.objects.create(name='Isolated Network')

        with impersonate(bull_bot):
            Team.objects.get_or_create(name='community.general maintainers', defaults={'organization': galaxy})

        ig_admin, _ = RoleDefinition.objects.get_or_create(
            name='AWX InstanceGroup admin',
            permissions=['change_instancegroup', 'delete_instancegroup', 'view_instancegroup'],
            defaults={'content_type': DABContentType.objects.get_for_model(InstanceGroup)},
        )

        org_admin_user, _ = User.objects.get_or_create(username='org_admin')
        ig_admin_user, _ = User.objects.get_or_create(username='instance_group_admin')
        RoleDefinition.objects.managed.org_admin.give_permission(org_admin_user, awx)
        ig_admin.give_permission(ig_admin_user, isolated_group)
        for user in (org_admin_user, ig_admin_user, spud):
            user.set_password('password')
            user.save()

        # Give some users team member and give that team some inventory object permissions
        for user in (spud, team_member):
            RoleDefinition.objects.managed.team_member.give_permission(spud, awx_devs)

        with impersonate(bull_bot):
            inv_admin, _ = RoleDefinition.objects.get_or_create(
                name='Inventory Admin',
                permissions=['change_inventory', 'view_inventory'],
                defaults={'content_type': permission_registry.content_type_model.objects.get_for_model(Inventory)},
            )
        for inv in (awx_inv, galaxy_inv):
            inv_admin.give_permission(awx_devs, inv)

        OAuth2Application.objects.get_or_create(
            name="Demo OAuth2 Application",
            description="Demo OAuth2 Application",
            redirect_uris="https://example.com/callback",
            authorization_grant_type="authorization-code",
            client_type="confidential",
        )

        self.stdout.write('Finished creating demo data!')

        if environ.get('LARGE') and not Organization.objects.filter(name__startswith='large').exists():
            self.create_large(settings.DEMO_DATA_COUNTS)
