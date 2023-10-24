try:
    from tabulate import tabulate

    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils.timezone import now

from ansible_base.models import Authenticator, AuthenticatorUser

User = get_user_model()


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
        admin_created = None
        admin_user = User.objects.filter(username="admin").first()
        if not admin_user:
            user, admin_created = User.objects.update_or_create(
                username="admin",
                is_superuser=True,
                first_name='Local',
                last_name='Admin',
                password='admin',
            )
            self.stdout.write("Created admin user with password 'admin'")

        existing_authenticator = Authenticator.objects.filter(type="local").first()
        if not existing_authenticator:
            existing_authenticator = Authenticator.objects.create(
                name='Local Database Authenticator',
                enabled=True,
                create_objects=True,
                configuration={},
                created_by=admin_user,
                created_on=now(),
                modified_by=admin_user,
                modified_on=now(),
                remove_users=False,
                type='local',
            )
            self.stdout.write("Created default local authenticator")

        if admin_created:
            AuthenticatorUser.objects.get_or_create(
                uid='admin',
                user=user,
                provider=existing_authenticator,
            )
