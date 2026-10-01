"""the look-ahead child id-list query is filtered to the created object."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

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


@pytest.mark.django_db
def test_child_id_list_query_is_narrowed_to_new_object(rando, organization, team, org_inv_rd, member_rd):
    """The look-ahead must not fetch every child id of the organization."""
    for i in range(20):
        Inventory.objects.create(name=f'inv-{i}', organization=organization)
    org_inv_rd.give_permission(team, organization)
    member_rd.give_permission(rando, team)

    with CaptureQueriesContext(connection) as ctx:
        new_inv = Inventory.objects.create(name='inv-new', organization=organization)

    child_queries = [q['sql'] for q in ctx.captured_queries if q['sql'].startswith('SELECT') and '"test_app_inventory"."organization_id"' in q['sql']]
    assert child_queries, 'expected the recompute to look up inventories of the organization'
    for sql in child_queries:
        assert f'"test_app_inventory"."id" = {new_inv.pk}' in sql, sql

    # and the new inventory did get its evaluations through the org role and the team member role
    org_role = ObjectRole.objects.get(role_definition=org_inv_rd, object_id=organization.pk)
    member_role = ObjectRole.objects.get(role_definition=member_rd, object_id=team.pk)
    for role in (org_role, member_role):
        assert RoleEvaluation.objects.filter(role=role, content_type_id=_inv_ct_id(), object_id=new_inv.pk, codename='change_inventory').exists()


@pytest.mark.django_db
def test_create_matches_full_recompute(rando, organization, team, org_inv_rd, member_rd):
    org_inv_rd.give_permission(team, organization)
    member_rd.give_permission(rando, team)
    for i in range(5):
        Inventory.objects.create(name=f'inv-{i}', organization=organization)
    after_create = _evaluation_rows()
    recompute_all_role_evaluations()
    assert _evaluation_rows() == after_create


@pytest.mark.django_db
def test_remote_child_id_list_query_is_narrowed(rando, organization):
    """Remote children (objects of another service with a parent_reference) take the same look-ahead filter."""
    from ansible_base.rbac.models import DABContentType, DABPermission, RoleDefinition
    from ansible_base.rbac.prefetch import TypesPrefetch
    from ansible_base.rbac.remote import RemoteObject

    org_ct = DABContentType.objects.get_for_model(Organization)
    foo_type = DABContentType.objects.create(service='foo', model='foo', app_label='foo', parent_content_type=org_ct)
    perms = [DABPermission.objects.create(codename=c, content_type=foo_type) for c in ('view_foo', 'change_foo')]
    foo_rd = RoleDefinition.objects.create_from_permissions(name='foo viewer', permissions=[perms[0].api_slug], content_type=foo_type)
    for oid in (42, 43):
        foo_rd.give_permission(rando, RemoteObject(content_type=foo_type, object_id=oid, parent_reference=organization.pk))
    org_foo_rd = RoleDefinition.objects.create_from_permissions(
        name='org foo', permissions=[perms[0].api_slug, perms[1].api_slug, 'shared.view_organization'], content_type=org_ct
    )
    org_foo_rd.give_permission(rando, organization)
    org_role = ObjectRole.objects.get(role_definition=org_foo_rd, object_id=organization.pk)

    with CaptureQueriesContext(connection) as ctx:
        expected = org_role.expected_direct_permissions(TypesPrefetch.from_db(), object_pk=42, object_ct_id=foo_type.id)

    assert expected == {('view_foo', foo_type.id, 42), ('change_foo', foo_type.id, 42)}
    remote_queries = [q['sql'] for q in ctx.captured_queries if '"dab_rbac_objectrole"."parent_reference"' in q['sql']]
    assert remote_queries
    for sql in remote_queries:
        assert '"dab_rbac_objectrole"."object_id" = \'42\'' in sql, sql
