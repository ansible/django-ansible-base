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

from sys import exit

try:
    from tabulate import tabulate

    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from ansible_base.authentication.models import Authenticator, AuthenticatorUser


class Command(BaseCommand):
    help = "Initialize service configuration with an admin user and a local authenticator"

    def add_arguments(self, parser):
        parser.add_argument("--list", action="store_true", help="list the authenticators", required=False)
        parser.add_argument("--initialize", action="store_true", help="Initialize an admin user and local db authenticator", required=False)
        parser.add_argument("--enable", type=int, help="Initialize an admin user and local db authenticator", required=False)
        parser.add_argument("--disable", type=int, help="Initialize an admin user and local db authenticator", required=False)

    def handle(self, *args, **options):
        took_action = False
        if options["initialize"]:
            self.initialize_authenticators()
            took_action = True
        if options["enable"] or options['disable']:
            for id, state in [(options['enable'], True), (options['disable'], False)]:
                if not id:
                    continue
                try:
                    authenticator = Authenticator.objects.get(id=id)
                except Authenticator.DoesNotExist:
                    raise CommandError(f"Authenticator {id} does not exist")
                if authenticator.enabled is not state:
                    authenticator.enabled = state
                    authenticator.save()
            took_action = True
        if options["list"] or not took_action:
            self.list_authenticators()

    def list_authenticators(self):
        authenticators = []
        headers = ["ID", "Enabled", "Name", "Order"]

        for authenticator in Authenticator.objects.all().order_by('id'):
            authenticators.append([f'{authenticator.id}', f'{authenticator.enabled}', authenticator.name, f'{authenticator.order}'])

        self.stdout.write('')
        if HAS_TABULATE:
            self.stdout.write(tabulate(authenticators, headers, tablefmt="github"))
        else:
            self.stdout.write("\t".join(headers))
            for authenticator_data in authenticators:
                self.stdout.write("\t".join(authenticator_data))
        self.stdout.write('')

    def initialize_authenticators(self):
        admin_user = get_user_model().objects.filter(username="admin").first()
        if not admin_user:
            self.stderr.write("No admin user exists")
            exit(255)

        existing_authenticator = Authenticator.objects.filter(type="ansible_base.authentication.authenticator_plugins.local").first()
        if not existing_authenticator:
            existing_authenticator = Authenticator.objects.create(
                name='Local Database Authenticator',
                enabled=True,
                create_objects=True,
                configuration={},
                created_by=admin_user,
                modified_by=admin_user,
                remove_users=False,
                type='ansible_base.authentication.authenticator_plugins.local',
            )
            self.stdout.write("Created default local authenticator")

            AuthenticatorUser.objects.get_or_create(
                uid=admin_user.username,
                user=admin_user,
                provider=existing_authenticator,
            )
