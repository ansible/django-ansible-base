import pytest

from ansible_base.rbac.models import RoleDefinition
from ansible_base.rbac.permission_registry import permission_registry
from test_app.models import UUIDModel


@pytest.fixture
def uuid_obj(organization):
    return UUIDModel.objects.create(organization=organization)


@pytest.fixture
def uuid_rd():
    rd, _ = RoleDefinition.objects.get_or_create(
        permissions=['change_uuidmodel', 'view_uuidmodel', 'delete_uuidmodel', 'view_manualextrauuidmodel'],
        name='manage UUID model',
        content_type=permission_registry.content_type_model.objects.get_for_model(UUIDModel),
    )
    return rd
