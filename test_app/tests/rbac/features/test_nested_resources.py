import pytest

from ansible_base.rbac.models import RoleDefinition
from ansible_base.rbac.permission_registry import permission_registry
from test_app.models import CollectionImport, Namespace, Organization


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
def test_grandparent_assignment(rando, organization, namespace, collection):
    rd, _ = RoleDefinition.objects.get_or_create(
        permissions=['change_collectionimport', 'delete_collectionimport', 'add_collectionimport', 'view_collectionimport', 'view_namespace'],
        name='collection-manager',
        content_type=permission_registry.content_type_model.objects.get_for_model(organization),
    )
    rd.give_permission(rando, organization)
    assert rando.has_obj_perm(collection, 'change_collectionimport')

    assert rando.has_obj_perm(namespace, 'add_collectionimport')
    assert rando.has_obj_perm(organization, 'add_collectionimport')

    assert set(Organization.access_qs(rando, 'add_collectionimport')) == set([organization])


@pytest.mark.django_db
def test_parent_assignment(rando, organization, namespace, collection):
    rd, _ = RoleDefinition.objects.get_or_create(
        permissions=['change_collectionimport', 'delete_collectionimport', 'add_collectionimport', 'view_collectionimport', 'view_namespace'],
        name='collection-manager',
        content_type=permission_registry.content_type_model.objects.get_for_model(namespace),
    )
    rd.give_permission(rando, namespace)
    assert rando.has_obj_perm(collection, 'change_collectionimport')

    assert rando.has_obj_perm(namespace, 'add_collectionimport')
    assert not rando.has_obj_perm(organization, 'add_collectionimport')

    assert set(Namespace.access_qs(rando, 'add_collectionimport')) == set([namespace])


@pytest.mark.django_db
def test_creator_permissions_for_parent(rando, organization, namespace, collection):
    RoleDefinition.objects.give_creator_permissions(rando, namespace)
    assert rando.has_obj_perm(namespace, 'change_namespace')  # would be the same without nesting
    assert rando.has_obj_perm(namespace, 'add_collectionimport')
    assert rando.has_obj_perm(collection, 'change_collectionimport')


@pytest.mark.django_db
def test_later_create_child_obj(namespace):
    "Very synthetic test, but makes sure that __init__ surprises do not throw errors"
    collection = CollectionImport(name='bar', namespace=namespace)
    delattr(collection, '__rbac_original_parent_id')
    collection.save()
