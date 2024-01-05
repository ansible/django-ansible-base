import pytest

from ansible_base.models.rbac import RoleDefinition
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.tests.functional.models import CollectionImport, Namespace, Organization


@pytest.fixture
def namespace(organization):
    return Namespace.objects.create(name='foo', organization=organization)


@pytest.fixture
def collection(namespace):
    return CollectionImport.objects.create(name='bar', namespace=namespace)


def test_parent_resource_utils():
    assert permission_registry.get_parent_fd_name(CollectionImport) == 'namespace'
    assert permission_registry.get_parent_fd_name(Namespace) == 'organization'

    assert permission_registry.get_parent_model(CollectionImport) == Namespace
    assert permission_registry.get_parent_model(Namespace) == Organization

    assert ('organization', Namespace) in permission_registry.get_child_models(Organization)
    assert ('namespace__organization', CollectionImport) in permission_registry.get_child_models(Organization)


@pytest.mark.django_db
def test_grandparent_assignment(rando, organization, collection):
    rd, _ = RoleDefinition.objects.get_or_create(
        permissions=['change_collectionimport', 'delete_collectionimport', 'add_collectionimport', 'view_collectionimport', 'view_namespace'],
        name='collection-manager',
    )
    rd.give_permission(rando, organization)
    assert rando.has_obj_perm(collection, 'change_collectionimport')
