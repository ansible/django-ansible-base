"""moving a grandchild object recomputes the roles of its OLD grandparent too."""

import pytest
from django.db import connection

from ansible_base.rbac.caching import recompute_all_role_evaluations
from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleEvaluation
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.triggers import post_save_update_obj_permissions
from test_app.models import CollectionImport, Namespace, Organization


def _evaluation_rows():
    return set(RoleEvaluation.objects.values_list("role_id", "codename", "content_type_id", "object_id"))


@pytest.mark.django_db
def test_single_grandchild_move_drops_old_org_rows(rando):
    """One collection moves to a namespace in another org; the old org's role must lose its rows for it.
    (The existing swap test only passed because the second move's full recompute cleaned up after the first.)"""
    rd = RoleDefinition.objects.create_from_permissions(
        permissions=['change_collectionimport', 'view_collectionimport', 'view_namespace'],
        name='collection-manager',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    )
    orgs = [Organization.objects.create(name=f'org-{i}') for i in range(2)]
    namespaces = [Namespace.objects.create(name=f'ns-{i}', organization=orgs[i]) for i in range(2)]
    collection = CollectionImport.objects.create(name='c', namespace=namespaces[0])
    rd.give_permission(rando, orgs[0])
    assert rando.has_obj_perm(collection, 'change_collectionimport')

    collection.namespace = namespaces[1]
    collection.save()

    assert not rando.has_obj_perm(collection, 'change_collectionimport')
    old_role = ObjectRole.objects.get(role_definition=rd, object_id=orgs[0].pk)
    ci_ct = permission_registry.content_type_model.objects.get_for_model(CollectionImport).id
    assert not RoleEvaluation.objects.filter(role=old_role, content_type_id=ci_ct, object_id=collection.pk).exists()
    after = _evaluation_rows()
    recompute_all_role_evaluations()
    assert _evaluation_rows() == after


@pytest.mark.django_db
def test_grandchild_move_when_old_parent_is_deleted_mid_move(rando):
    """The old namespace is deleted after the move is written but before its post_save recompute runs
    (two requests racing). The old org's role must still lose its rows for the moved collection."""
    rd = RoleDefinition.objects.create_from_permissions(
        permissions=['change_collectionimport', 'view_collectionimport', 'view_namespace'],
        name='collection-manager',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    )
    orgs = [Organization.objects.create(name=f'org-{i}') for i in range(2)]
    namespaces = [Namespace.objects.create(name=f'ns-{i}', organization=orgs[i]) for i in range(2)]
    collection = CollectionImport.objects.get(pk=CollectionImport.objects.create(name='c', namespace=namespaces[0]).pk)
    rd.give_permission(rando, orgs[0])
    assert rando.has_obj_perm(collection, 'change_collectionimport')

    # The move is written, but its post_save recompute has not run yet
    collection.namespace = namespaces[1]
    CollectionImport.objects.filter(pk=collection.pk).update(namespace=namespaces[1])
    # Another request deletes the old namespace in that window; the collection no longer belongs to it
    Namespace.objects.filter(pk=namespaces[0].pk).delete()
    post_save_update_obj_permissions(collection)

    assert not rando.has_obj_perm(collection, 'change_collectionimport')
    after = _evaluation_rows()
    recompute_all_role_evaluations()
    assert _evaluation_rows() == after


def _fail_on_namespace_read(execute, sql, params, many, context):
    assert f'FROM "{Namespace._meta.db_table}"' not in sql, f'creating a collection read its namespace again: {sql}'
    return execute(sql, params, many, context)


@pytest.mark.django_db
def test_creating_a_grandchild_does_not_load_its_parent_again():
    """On create the original parent is the current parent, so the old-parent handling must not run."""
    org = Organization.objects.create(name='org')
    namespace = Namespace.objects.create(name='ns', organization=org)
    with connection.execute_wrapper(_fail_on_namespace_read):
        CollectionImport.objects.create(name='c', namespace=namespace)
