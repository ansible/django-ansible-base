"""moving a grandchild object recomputes the roles of its OLD grandparent too."""

import pytest

from ansible_base.rbac.caching import recompute_all_role_evaluations
from ansible_base.rbac.models import ObjectRole, RoleEvaluation
from ansible_base.rbac.permission_registry import permission_registry
from test_app.models import Inventory, Organization


def _inv_ct_id():
    return permission_registry.content_type_model.objects.get_for_model(Inventory).id


def _org_ct_id():
    return permission_registry.content_type_model.objects.get_for_model(Organization).id


def _evaluation_rows():
    return set(RoleEvaluation.objects.values_list("role_id", "codename", "content_type_id", "object_id"))


from ansible_base.rbac.models import RoleDefinition  # noqa: E402
from test_app.models import CollectionImport, Namespace  # noqa: E402


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
