"""the created-object recompute applies to every registered child type (direct children, grandchildren, UUID-keyed, teams)."""

import pytest

from ansible_base.rbac.caching import recompute_all_role_evaluations
from ansible_base.rbac.models import ObjectRole, RoleEvaluation
from ansible_base.rbac.permission_registry import permission_registry
from test_app.models import Inventory, Organization, Team


def _inv_ct_id():
    return permission_registry.content_type_model.objects.get_for_model(Inventory).id


def _org_ct_id():
    return permission_registry.content_type_model.objects.get_for_model(Organization).id


def _evaluation_rows():
    return set(RoleEvaluation.objects.values_list("role_id", "codename", "content_type_id", "object_id"))


from ansible_base.rbac.models import RoleDefinition  # noqa: E402
from test_app.models import CollectionImport, Namespace, UUIDModel  # noqa: E402


def _org_rd(name, permissions):
    return RoleDefinition.objects.create_from_permissions(
        permissions=permissions, name=name, content_type=permission_registry.content_type_model.objects.get_for_model(Organization)
    )


@pytest.mark.django_db
def test_created_namespace_matches_full_recompute(rando, organization, team, member_rd):
    rd = _org_rd('org-ns', ['view_organization', 'view_namespace', 'change_namespace'])
    rd.give_permission(team, organization)
    member_rd.give_permission(rando, team)
    ns = Namespace.objects.create(name='ns', organization=organization)
    member_role = ObjectRole.objects.get(role_definition=member_rd, object_id=team.pk)
    ns_ct = permission_registry.content_type_model.objects.get_for_model(Namespace).id
    assert RoleEvaluation.objects.filter(role=member_role, content_type_id=ns_ct, object_id=ns.pk, codename='change_namespace').exists()
    after = _evaluation_rows()
    recompute_all_role_evaluations()
    assert _evaluation_rows() == after


@pytest.mark.django_db
def test_created_grandchild_matches_full_recompute(rando, organization, team, member_rd):
    """CollectionImport's parent is Namespace whose parent is Organization: a two-level parent chain."""
    rd = _org_rd('org-ci', ['view_organization', 'view_namespace', 'view_collectionimport', 'change_collectionimport'])
    rd.give_permission(team, organization)
    member_rd.give_permission(rando, team)
    ns = Namespace.objects.create(name='ns', organization=organization)
    ci = CollectionImport.objects.create(name='ci', namespace=ns)
    member_role = ObjectRole.objects.get(role_definition=member_rd, object_id=team.pk)
    ci_ct = permission_registry.content_type_model.objects.get_for_model(CollectionImport).id
    assert RoleEvaluation.objects.filter(role=member_role, content_type_id=ci_ct, object_id=ci.pk, codename='change_collectionimport').exists()
    after = _evaluation_rows()
    recompute_all_role_evaluations()
    assert _evaluation_rows() == after


@pytest.mark.django_db
def test_created_uuid_child_matches_full_recompute(rando, organization, team, member_rd):
    """UUID-keyed children are cached in RoleEvaluationUUID; the created path must write there."""
    from ansible_base.rbac.models import RoleEvaluationUUID

    rd = _org_rd('org-uuid', ['view_organization', 'view_uuidmodel', 'change_uuidmodel'])
    rd.give_permission(team, organization)
    member_rd.give_permission(rando, team)
    obj = UUIDModel.objects.create(organization=organization)
    member_role = ObjectRole.objects.get(role_definition=member_rd, object_id=team.pk)
    uuid_ct = permission_registry.content_type_model.objects.get_for_model(UUIDModel).id
    assert RoleEvaluationUUID.objects.filter(role=member_role, content_type_id=uuid_ct, object_id=obj.pk, codename='change_uuidmodel').exists()
    before = set(RoleEvaluationUUID.objects.values_list('role_id', 'codename', 'object_id'))
    recompute_all_role_evaluations()
    assert set(RoleEvaluationUUID.objects.values_list('role_id', 'codename', 'object_id')) == before


@pytest.mark.django_db
def test_created_team_matches_full_recompute(rando, organization, org_inv_rd, member_rd, org_team_member_rd):
    """Creating a team both recomputes team membership and runs the created-object path for the team object."""
    org_team_member_rd.give_permission(rando, organization)
    Inventory.objects.create(name='inv', organization=organization)
    new_team = Team.objects.create(name='new-team', organization=organization)
    org_inv_rd.give_permission(new_team, organization)
    after = _evaluation_rows()
    recompute_all_role_evaluations()
    assert _evaluation_rows() == after
    org_member_role = ObjectRole.objects.get(role_definition=org_team_member_rd, object_id=organization.pk)
    assert new_team in org_member_role.provides_teams.all()
