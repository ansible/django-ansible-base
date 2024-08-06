import pytest

from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleEvaluation, RoleEvaluationUUID, RoleUserAssignment, get_evaluation_model
from ansible_base.rbac.permission_registry import permission_registry
from test_app.models import Organization, UUIDModel


@pytest.fixture
def view_uuid_rd():
    rd, _ = RoleDefinition.objects.get_or_create(
        permissions=['view_uuidmodel'], name='see UUID model', content_type=permission_registry.content_type_model.objects.get_for_model(UUIDModel)
    )
    return rd


@pytest.mark.django_db
def test_get_evaluation_model(uuid_obj):
    assert get_evaluation_model(UUIDModel) == RoleEvaluationUUID
    assert get_evaluation_model(Organization) == RoleEvaluation
    assert get_evaluation_model(uuid_obj) == RoleEvaluationUUID
    assert get_evaluation_model(uuid_obj.organization) == RoleEvaluation


@pytest.mark.django_db
def test_duplicate_assignment(rando, view_uuid_rd, uuid_obj):
    assignment = view_uuid_rd.give_permission(rando, uuid_obj)
    assert ObjectRole.objects.count() == 1
    assert assignment.content_object == uuid_obj
    assert assignment.object_role.content_object == uuid_obj

    # duplicate assignments should return existing assignment
    assignment = view_uuid_rd.give_permission(rando, uuid_obj)
    assert ObjectRole.objects.count() == 1
    assert assignment.content_object == uuid_obj
    assert assignment.object_role.content_object == uuid_obj


@pytest.mark.django_db
def test_filter_uuid_model(rando, organization, view_uuid_rd):
    uuid_objs = [UUIDModel.objects.create(organization=organization) for i in range(5)]
    view_uuid_rd.give_permission(rando, uuid_objs[1])
    view_uuid_rd.give_permission(rando, uuid_objs[3])

    assert rando.has_obj_perm(uuid_objs[1], 'view')
    assert set(UUIDModel.access_qs(rando)) == {uuid_objs[1], uuid_objs[3]}


@pytest.mark.django_db
def test_organization_uuid_model_permission(rando):
    rd, _ = RoleDefinition.objects.get_or_create(
        permissions=['add_uuidmodel', 'view_uuidmodel', 'view_organization'],
        name='org-see UUID model',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    )
    uuid_objs = []
    orgs = []
    for i in range(3):
        orgs.append(Organization.objects.create(name=f'org-{i}'))
        uuid_objs.append(UUIDModel.objects.create(organization=orgs[i]))
    rd.give_permission(rando, orgs[1])

    assert rando.has_obj_perm(uuid_objs[1], 'view')
    assert list(UUIDModel.access_qs(rando)) == [uuid_objs[1]]

    assert rando.has_obj_perm(orgs[1], 'add_uuidmodel')
    assert list(Organization.access_qs(rando, 'add_uuidmodel')) == [orgs[1]]


@pytest.mark.django_db
def test_add_uuid_permission_to_role(rando, organization, uuid_obj):
    rd, _ = RoleDefinition.objects.get_or_create(
        permissions=['view_organization'], name='will change', content_type=permission_registry.content_type_model.objects.get_for_model(Organization)
    )
    rd.give_permission(rando, organization)
    assert not rando.has_obj_perm(uuid_obj, 'view')

    perm = permission_registry.permission_qs.get(codename='view_uuidmodel')
    rd.permissions.add(perm)
    assert rando.has_obj_perm(uuid_obj, 'view')


@pytest.mark.django_db
def test_visible_items_with_uuid(rando, organization, view_uuid_rd):
    uuid_objs = [UUIDModel.objects.create(organization=organization) for i in range(5)]
    assignment1 = view_uuid_rd.give_permission(rando, uuid_objs[1])
    assignment3 = view_uuid_rd.give_permission(rando, uuid_objs[3])

    assert set(ObjectRole.visible_items(rando)) == set([assignment1.object_role, assignment3.object_role])
    assert set(RoleUserAssignment.visible_items(rando)) == set([assignment1, assignment3])
