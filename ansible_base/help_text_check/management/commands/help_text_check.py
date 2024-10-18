from sys import exit

from django.apps import apps
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ensure models have help_text fields"
    ignore_reasons = {}
    global_ignore_fields = ['id']
    indentation = "    "

    def add_arguments(self, parser):
        parser.add_argument(
            "--applications",
            type=str,
            help="Comma delimited list of the django application to check. If not specified all applications will be checked",
            required=False,
        )
        parser.add_argument("--ignore-file", type=str, help="The path to a file containing entries like: app.model.field to ignore", required=False)
        parser.add_argument("--skip-global-ignore", action="store_true", help="Don't ignore the global ignore fields", required=False)

    def get_models(self, applications):
        installed_applications = apps.app_configs.keys()
        models = []
        for requested_application in applications.split(','):
            found_app = False
            for installed_application in installed_applications:
                if requested_application in installed_application:
                    found_app = True
                    for model in apps.get_app_config(installed_application).get_models():
                        if model not in models:
                            models.append(model)
            if not found_app:
                self.stderr.write(self.style.WARNING(f"Specified application {requested_application} is not in INSTALLED_APPS"))
        return models

    def handle(self, *args, **options):
        ignore_file = options.get('ignore_file', None)
        if ignore_file:
            try:
                with open(ignore_file, 'r') as f:
                    for line in f.readlines():
                        elements = line.strip().split('#', 2)
                        line = elements[0].strip()
                        if line:
                            self.ignore_reasons[line] = elements[1] if len(elements) == 2 else 'Not specified'
            except FileNotFoundError:
                self.stderr.write(self.style.ERROR(f"Ignore file {ignore_file} does not exist"))
                exit(255)
            except PermissionError:
                self.stderr.write(self.style.ERROR(f"No permission to read {ignore_file}"))
                exit(255)
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Failed to read {ignore_file}: {e}"))
                exit(255)

            if len(self.ignore_reasons) > 0:
                self.stdout.write(f"Ignoring {len(self.ignore_reasons)} field(s):")
                for field in self.ignore_reasons.keys():
                    self.stdout.write(f"{self.indentation}- {field}")
                print("")

        applications = options.get('applications', None)
        if applications:
            models = self.get_models(applications)
        else:
            models = apps.get_models()

        scanned_models = 0
        return_code = 0
        results = {}
        for model in models:
            scanned_models = scanned_models + 1

            model_name = f"{model._meta.app_label}.{model.__name__}"
            results[model_name] = {}
            for field in model._meta.concrete_fields:
                field_name = f"{model_name}.{field.name}"

                help_text = getattr(field, 'help_text', '')
                if field_name in self.ignore_reasons:
                    message = self.style.WARNING(f"{self.indentation}{field.name}: {self.ignore_reasons[field_name]}")
                elif field.name in self.global_ignore_fields and not options.get('skip_global_ignore', False):
                    message = self.style.WARNING(f"{self.indentation}{field.name}: global ignore field")
                elif not help_text:
                    return_code = 1
                    message = self.style.MIGRATE_HEADING(f"{self.indentation}{field.name}: ") + self.style.ERROR("missing help_text")
                else:
                    message = self.style.SUCCESS(f"{self.indentation}{field.name}") + f": {help_text}"

                results[model_name][field.name] = message
        self.stdout.write(f"Scanned: {scanned_models} model(s)")

        for model_name in sorted(results.keys()):
            self.stdout.write(self.style.SQL_TABLE(model_name))
            for field_name in sorted(results[model_name].keys()):
                self.stdout.write(results[model_name][field_name])
            self.stdout.write("")

        exit(return_code)
