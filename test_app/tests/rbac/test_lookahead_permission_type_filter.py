"""in look-ahead mode, team-held roles whose definition cannot grant on the object type are skipped."""

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
from ansible_base.rbac.prefetch import TypesPrefetch  # noqa: E402
from test_app.models import CollectionImport, Namespace  # noqa: E402


def _org_rd(name, permissions):
    return RoleDefinition.objects.create_from_permissions(
        permissions=permissions, name=name, content_type=permission_registry.content_type_model.objects.get_for_model(Organization)
    )


@pytest.mark.django_db
def test_role_definition_ids_granting(org_inv_rd, member_rd):
    ns_rd = _org_rd('org-ns', ['view_organization', 'view_namespace', 'change_namespace'])
    add_ci_rd = _org_rd('org-add-ci', ['view_organization', 'view_namespace', 'add_collectionimport', 'view_collectionimport'])
    tp = TypesPrefetch.from_db()
    inv_ct = permission_registry.content_type_model.objects.get_for_model(Inventory).id
    ns_ct = permission_registry.content_type_model.objects.get_for_model(Namespace).id
    ci_ct = permission_registry.content_type_model.objects.get_for_model(CollectionImport).id
    assert org_inv_rd.id in tp.role_definition_ids_granting(inv_ct)
    assert ns_rd.id not in tp.role_definition_ids_granting(inv_ct)
    assert member_rd.id not in tp.role_definition_ids_granting(inv_ct)
    # an add-permission on a grandchild type grants (the add evaluation) on the child type
    assert add_ci_rd.id in tp.role_definition_ids_granting(ns_ct)
    assert add_ci_rd.id in tp.role_definition_ids_granting(ci_ct)
    assert ns_rd.id not in tp.role_definition_ids_granting(ci_ct)


@pytest.mark.django_db
def test_role_definition_ids_granting_remote_and_unregistered_types(org_inv_rd):
    """An add-permission on a remote type grants on that type's declared parent; a permission on a
    model outside the permission registry is ignored instead of raising."""
    from django.contrib.auth import get_user_model

    from ansible_base.rbac.models import DABContentType, DABPermission
    from ansible_base.rbac.models.content_type import get_local_resource_prefix

    org_ct = DABContentType.objects.get_for_model(Organization)
    foo_type = DABContentType.objects.create(service='foo', model='foo', app_label='foo', parent_content_type=org_ct)
    add_foo = DABPermission.objects.create(codename='add_foo', content_type=foo_type)
    remote_rd = RoleDefinition.objects.create(name='org adds foos', content_type=org_ct)
    remote_rd.permissions.add(add_foo)

    # a local model that is not in the permission registry: a content type row for it
    # would only exist if some other app created one, so create it directly
    user_model = get_user_model()
    user_ct = DABContentType.objects.create(service=get_local_resource_prefix(), app_label=user_model._meta.app_label, model=user_model._meta.model_name)
    assert not user_ct.is_remote
    add_user = DABPermission.objects.create(codename='add_user', content_type=user_ct)
    odd_rd = RoleDefinition.objects.create(name='odd', content_type=None)
    odd_rd.permissions.add(add_user)

    tp = TypesPrefetch.from_db()
    assert remote_rd.id in tp.role_definition_ids_granting(org_ct.id)
    assert odd_rd.id not in tp.role_definition_ids_granting(org_ct.id)
    assert odd_rd.id not in tp.role_definition_ids_granting(permission_registry.content_type_model.objects.get_for_model(Inventory).id)


@pytest.mark.django_db
def test_irrelevant_team_roles_are_not_visited(rando, organization, team, org_inv_rd, member_rd):
    """Five org roles per team, one with inventory permissions: only that one is loaded for an inventory create."""
    others = [_org_rd(f'org-other-{i}', ['view_organization', 'view_namespace', 'change_namespace']) for i in range(4)]
    for rd in others + [org_inv_rd]:
        rd.give_permission(team, organization)
    member_rd.give_permission(rando, team)
    member_role = ObjectRole.objects.get(role_definition=member_rd, object_id=team.pk)

    calls = []
    original = ObjectRole.expected_direct_permissions

    def counting(self, *args, **kwargs):
        calls.append(self.role_definition_id)
        return original(self, *args, **kwargs)

    from unittest.mock import patch

    with patch.object(ObjectRole, 'expected_direct_permissions', counting):
        new_inv = Inventory.objects.create(name='inv-new', organization=organization)
    assert org_inv_rd.id in calls
    assert not any(rd.id in calls for rd in others)
    assert RoleEvaluation.objects.filter(role=member_role, object_id=new_inv.pk, content_type_id=_inv_ct_id(), codename='change_inventory').exists()
    after = _evaluation_rows()
    recompute_all_role_evaluations()
    assert _evaluation_rows() == after


@pytest.mark.django_db
def test_grandchild_add_permission_still_granted(rando, organization, team, member_rd):
    """An org role with only add_collectionimport must still produce the add evaluation on a new namespace."""
    add_ci_rd = _org_rd('org-add-ci', ['view_organization', 'view_namespace', 'add_collectionimport', 'view_collectionimport'])
    add_ci_rd.give_permission(team, organization)
    member_rd.give_permission(rando, team)
    ns = Namespace.objects.create(name='ns', organization=organization)
    after = _evaluation_rows()
    recompute_all_role_evaluations()
    assert _evaluation_rows() == after
    member_role = ObjectRole.objects.get(role_definition=member_rd, object_id=team.pk)
    ns_ct = permission_registry.content_type_model.objects.get_for_model(Namespace).id
    assert RoleEvaluation.objects.filter(role=member_role, content_type_id=ns_ct, object_id=ns.pk, codename='add_collectionimport').exists()
