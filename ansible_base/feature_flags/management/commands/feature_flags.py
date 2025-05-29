try:
    from tabulate import tabulate

    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

from django.core.management.base import BaseCommand
from flags.state import flag_state

from ansible_base.feature_flags.models import AAPFlag


class Command(BaseCommand):
    help = "AAP Feature Flag management command"

    def add_arguments(self, parser):
        parser.add_argument("--list", action="store_true", help="List feature flags", required=False)

    def handle(self, *args, **options):
        if options["list"]:
            self.list_feature_flags()

    def list_feature_flags(self):
        feature_flags = []
        headers = ["Name", "UI_Name", "Value", "State", "Support Level", "Visibility", "Toggle Type", "Description", "Support URL"]

        for feature_flag in AAPFlag.objects.all().order_by('name'):
            feature_flags.append(
                [
                    f'{feature_flag.name}',
                    f'{feature_flag.ui_name}',
                    f'{feature_flag.value}',
                    f'{flag_state(feature_flag.name)}',
                    f'{feature_flag.support_level}',
                    f'{feature_flag.visibility}',
                    f'{feature_flag.toggle_type}',
                    f'{feature_flag.description}',
                    f'{feature_flag.support_url}',
                ]
            )
        self.stdout.write('')

        if HAS_TABULATE:
            self.stdout.write(tabulate(feature_flags, headers, tablefmt="github"))
        else:
            self.stdout.write("\t".join(headers))
            for feature_flag in feature_flags:
                self.stdout.write("\t".join(feature_flag))
        self.stdout.write('')
