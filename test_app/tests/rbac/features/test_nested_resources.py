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


@pytest.fixture
def org_collection_rd():
    return RoleDefinition.objects.create_from_permissions(
        permissions=['change_collectionimport', 'delete_collectionimport', 'add_collectionimport', 'view_collectionimport', 'view_namespace'],
        name='collection-manager',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    )


def test_parent_resource_utils():
    assert permission_registry.get_parent_fd_name(CollectionImport) == 'namespace'
    assert permission_registry.get_parent_fd_name(Namespace) == 'organization'

    assert permission_registry.get_parent_model(CollectionImport) == Namespace
    assert permission_registry.get_parent_model(Namespace) == Organization

    assert ('organization', Namespace) in permission_registry.get_child_models(Organization)
    assert ('namespace__organization', CollectionImport) in permission_registry.get_child_models(Organization)


@pytest.mark.django_db
def test_grandparent_assignment(rando, organization, namespace, collection, org_collection_rd):
    org_collection_rd.give_permission(rando, organization)
    assert rando.has_obj_perm(collection, 'change_collectionimport')

    assert rando.has_obj_perm(namespace, 'add_collectionimport')
    assert rando.has_obj_perm(organization, 'add_collectionimport')

    assert set(Organization.access_qs(rando, 'add_collectionimport')) == set([organization])


@pytest.mark.django_db
def test_create_grandchild_object(rando, organization, namespace, org_collection_rd):
    org_collection_rd.give_permission(rando, organization)
    collection = CollectionImport.objects.create(name='bar', namespace=namespace)
    assert rando.has_obj_perm(collection, 'change_collectionimport')


@pytest.mark.django_db
@pytest.mark.parametrize('parent', ['namespace', 'organization'])
def test_move_grandchild_object(rando, org_collection_rd, parent):
    orgs = [Organization.objects.create(name=f'foo-{i}') for i in range(2)]
    namespaces = [Namespace.objects.create(name=f'foo-{i}', organization=orgs[i]) for i in range(2)]
    collections = [CollectionImport.objects.create(name=f'bar-{i}', namespace=namespaces[i]) for i in range(2)]

    org_collection_rd.give_permission(rando, orgs[0])
    assert rando.has_obj_perm(collections[0], 'change_collectionimport')
    assert not rando.has_obj_perm(collections[1], 'change_collectionimport')

    if parent == 'namespace':
        collections[0].namespace = namespaces[1]
        collections[0].save()
        collections[1].namespace = namespaces[0]
        collections[1].save()
    else:
        namespaces[0].organization = orgs[1]
        namespaces[0].save()
        namespaces[1].organization = orgs[0]
        namespaces[1].save()

    # In both cases, the two collections have switched organizations
    # and the rando user has permission to the first org, which now applies to the 2nd collection
    assert not rando.has_obj_perm(collections[0], 'change_collectionimport')
    assert rando.has_obj_perm(collections[1], 'change_collectionimport')


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
