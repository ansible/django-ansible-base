from django.core.management import call_command

from ansible_base.resource_registry.models import Resource
from ansible_base.resource_registry.models.service_identifier import ServiceID, service_id
from test_app.models import ResourceMigrationTestModel


def test_flush_restores_migration_prerequisites(transactional_db):
    cached_service_id = service_id()

    # Exercise the same flush used when a transactional test tears down.
    call_command('flush', interactive=False, verbosity=0)

    assert str(ServiceID.objects.get().pk) == cached_service_id
    assert ResourceMigrationTestModel.objects.filter(name='migration resource').exists()
    resource = Resource.objects.get(name='migration resource', content_type__resource_type__name='aap.resourcemigrationtestmodel')
    assert str(resource.service_id) == cached_service_id
