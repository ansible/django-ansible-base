import pytest

from ansible_base.rbac.caching import recompute_all_role_evaluations
from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleEvaluation, RoleEvaluationUUID
from ansible_base.rbac.permission_registry import permission_registry
from test_app.models import ExtraExtraUUIDModel, ManualExtraUUIDModel, UUIDModel


def _rows():
    return set(RoleEvaluation.objects.values_list('role_id', 'codename', 'content_type_id', 'object_id')) | set(
        RoleEvaluationUUID.objects.values_list('role_id', 'codename', 'content_type_id', 'object_id')
    )


@pytest.mark.django_db
@pytest.mark.parametrize('actor', ['user', 'team'])
def test_object_role_stores_str_pk(uuid_obj, uuid_rd, rando, team, actor):
    assignment = uuid_rd.give_permission(rando if actor == 'user' else team, uuid_obj)
    assert assignment.object_role.object_id == str(uuid_obj.pk)
    assert assignment.object_id == str(uuid_obj.pk)
    assert ObjectRole.objects.filter(object_id=uuid_obj.pk).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize('actor', ['user', 'team'])
def test_create_child_of_uuid_parent_matches_full_recompute(organization, uuid_obj, uuid_rd, team, rando, member_rd, org_inv_rd, actor):
    if actor == 'user':
        uuid_rd.give_permission(rando, uuid_obj)
    else:
        uuid_rd.give_permission(team, uuid_obj)
        org_inv_rd.give_permission(team, organization)
        member_rd.give_permission(rando, team)
    manual = ManualExtraUUIDModel.objects.create(uuidmodel_ptr=uuid_obj)
    assert rando.has_obj_perm(manual, 'view')
    after_create = _rows()
    recompute_all_role_evaluations()
    assert _rows() == after_create


@pytest.mark.django_db
def test_delete_uuid_object_removes_object_roles(uuid_obj, uuid_rd, rando):
    uuid_rd.give_permission(rando, uuid_obj)
    ct = permission_registry.content_type_model.objects.get_for_model(UUIDModel)
    uuid_obj.delete()
    assert not ObjectRole.objects.filter(content_type=ct).exists()


def _create_uuid_object(model, organization):
    uuid_obj = UUIDModel.objects.create(organization=organization)
    if model is UUIDModel:
        return uuid_obj
    manual = ManualExtraUUIDModel.objects.create(uuidmodel_ptr=uuid_obj)
    if model is ManualExtraUUIDModel:
        return manual
    return ExtraExtraUUIDModel.objects.create(extra_uuid=manual)


@pytest.mark.django_db
@pytest.mark.parametrize('model', [UUIDModel, ManualExtraUUIDModel, ExtraExtraUUIDModel])
@pytest.mark.parametrize('pk_format', [str, lambda u: str(u).upper(), lambda u: u.hex, lambda u: '{%s}' % u], ids=['str', 'upper', 'hex', 'braced'])
def test_non_canonical_in_memory_pk_is_stored_canonical(organization, rando, model, pk_format):
    obj = _create_uuid_object(model, organization)
    canonical = str(obj.pk)
    rd = RoleDefinition.objects.create_from_permissions(
        name=f'view {model._meta.model_name}',
        permissions=[f'view_{model._meta.model_name}'],
        content_type=permission_registry.content_type_model.objects.get_for_model(model),
    )
    obj.pk = pk_format(obj.pk)
    assignment = rd.give_permission(rando, obj)
    assert assignment.object_role.object_id == canonical
    assert assignment.object_id == canonical
    fresh = model.objects.get(pk=canonical)
    assert rando.has_obj_perm(fresh, 'view')
    rd.give_permission(rando, obj)
    assert ObjectRole.objects.filter(role_definition=rd).count() == 1
    rd.remove_permission(rando, obj)
    assert not rando.has_obj_perm(fresh, 'view')
