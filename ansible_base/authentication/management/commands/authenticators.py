try:
    from tabulate import tabulate

    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils.translation import gettext_lazy as _

from ansible_base.authentication.models import Authenticator
from ansible_base.lib.utils.models import get_system_user


class Command(BaseCommand):
    help = "Initialize service configuration with an admin user and a local authenticator"

    def add_arguments(self, parser):
        parser.add_argument("--list", action="store_true", help="List the authenticators", required=False)
        parser.add_argument("--initialize", action="store_true", help="Initialize an admin user and local db authenticator", required=False)
        parser.add_argument("--enable", type=int, help="Enable the authenticator with provided ID", required=False)
        parser.add_argument("--disable", type=int, help="Disable the authenticator with provided ID", required=False)

    def handle(self, *args, **options):
        took_action = False
        if options["initialize"]:
            self.initialize_authenticators()
            took_action = True
        if options["enable"] or options['disable']:
            for id, state in [(options['enable'], True), (options['disable'], False)]:
                if not id:
                    continue
                self._update_authenticator(id, state)
            took_action = True
        if options["list"] or not took_action:
            self.list_authenticators()

    def _update_authenticator(self, id: int, state: bool):
        try:
            authenticator = Authenticator.objects.get(id=id)
        except Authenticator.DoesNotExist:
            raise CommandError(_("Authenticator %(id)s does not exist") % {"id": id})
        if authenticator.enabled is not state:
            authenticator.enabled = state
            authenticator.save()

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
        if Authenticator.objects.filter(type="ansible_base.authentication.authenticator_plugins.local").exists():
            self.stdout.write("Local authenticator already exists, skipping")
            return

        # First try to get the system user
        system_user = get_system_user()
        admin_user = None
        try:
            admin_user = get_user_model().objects.filter(username="admin").first()
        except get_user_model().DoesNotExist:
            pass
        creator = None
        if system_user is not None:
            creator = system_user
        elif admin_user is not None:
            creator = admin_user
        else:
            creator = None
            self.stderr.write("Neither system user nor admin user were defined, local authenticator will be created without created_by set")

        Authenticator.objects.create(
            name='Local Database Authenticator',
            enabled=True,
            create_objects=True,
            configuration={},
            created_by=creator,
            modified_by=creator,
            remove_users=False,
            type='ansible_base.authentication.authenticator_plugins.local',
        )
        self.stdout.write("Created default local authenticator")
