from django.core.management.base import BaseCommand
from ansible_base.models import Resource, ResourceType, Permission

class Command(BaseCommand):
    help = "Reset resource index"

    def handle(self, *args, **options):
        ResourceType.objects.all().delete()

        ResourceType.update_resource_types_from_registry()
        Permission.update_permissions()
        Resource.update_index()