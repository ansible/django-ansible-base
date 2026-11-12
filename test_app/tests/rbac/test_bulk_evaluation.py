import pytest
from django.contrib.auth.models import AnonymousUser, Group
from django.test import override_settings
from rest_framework.exceptions import ValidationError

from ansible_base.rbac import permission_registry
from ansible_base.rbac.evaluations import get_object_permissions
from ansible_base.rbac.models import RoleDefinition
from ansible_base.rbac.triggers import defer_rbac_computations
from test_app.models import Inventory, UUIDModel

pytestmark = pytest.mark.django_db


def test_bulk_permissions_requires_registered_model(rando, django_assert_num_queries):
    with django_assert_num_queries(0), pytest.raises(ValidationError, match='group type is not registered with DAB RBAC'):
        get_object_permissions(rando, Group, [1])


def test_bulk_permissions_requires_user_or_team(inventory, django_assert_num_queries):
    with django_assert_num_queries(0), pytest.raises(RuntimeError, match='Evaluation methods are for users or teams'):
        get_object_permissions(inventory, Inventory, [inventory.pk])


@pytest.mark.parametrize('operation', ['create', 'delete'])
def test_bulk_permissions_with_deferred_changes(inventory, rando, org_inv_change_rd, operation, django_assert_num_queries):
    organization = inventory.organization
    org_inv_change_rd.give_permission(rando, organization)
    ids = [inventory.pk]
    expected = {inventory.pk: {'view_inventory', 'change_inventory'}}
    with defer_rbac_computations():
        assert get_object_permissions(rando, Inventory, ids) == expected
        if operation == 'create':
            created = Inventory.objects.create(name='Deferred inventory', organization=organization)
            ids.append(created.pk)
            expected[created.pk] = {'view_inventory', 'change_inventory'}
        else:
            expected[inventory.pk] = set()
            inventory.delete()
        with django_assert_num_queries(0), pytest.raises(RuntimeError, match='get_object_permissions cannot be called with deferred RBAC changes'):
            get_object_permissions(rando, Inventory, ids)
    assert get_object_permissions(rando, Inventory, ids) == expected


@pytest.mark.parametrize('model', [Inventory, UUIDModel])
def test_bulk_permissions(model, organization, rando, django_assert_num_queries):
    objects = [model.objects.create(organization=organization) for _ in range(25)]
    role = RoleDefinition.objects.create_from_permissions(
        name='bulk-change',
        permissions=[f'view_{model._meta.model_name}', f'change_{model._meta.model_name}'],
        content_type=permission_registry.content_type_model.objects.get_for_model(model),
    )
    role.give_permission(rando, objects[0])
    expected = {obj.pk: set() for obj in objects}
    expected[objects[0].pk] = {f'view_{model._meta.model_name}', f'change_{model._meta.model_name}'}
    with django_assert_num_queries(1):
        assert get_object_permissions(rando, model, [obj.pk for obj in objects]) == expected
    with django_assert_num_queries(0):
        assert get_object_permissions(rando, model, []) == {}


def test_bulk_queryset_and_inherited_permissions(inventory, rando, team, member_rd, org_inv_change_rd):
    member_rd.give_permission(rando, team)
    org_inv_change_rd.give_permission(team, inventory.organization)
    for actor in (rando, team):
        assert get_object_permissions(actor, Inventory, Inventory.objects.values_list('pk', flat=True)) == {
            inventory.pk: {'view_inventory', 'change_inventory'}
        }


@pytest.mark.parametrize('model', [Inventory, UUIDModel])
def test_bulk_permissions_filtered_codenames(model, organization, rando, django_assert_num_queries):
    obj = model.objects.create(organization=organization)
    name = model._meta.model_name
    role = RoleDefinition.objects.create_from_permissions(
        name='filtered-bulk-change',
        permissions=[f'view_{name}', f'change_{name}'],
        content_type=permission_registry.content_type_model.objects.get_for_model(model),
    )
    role.give_permission(rando, obj)
    # Exclude a granted permission and include a denied one in the same batch.
    with django_assert_num_queries(1) as queries:
        assert get_object_permissions(rando, model, [obj.pk], codenames=[f'change_{name}', f'delete_{name}']) == {obj.pk: {f'change_{name}'}}
    assert '"codename" IN' in queries.captured_queries[0]['sql']
    with django_assert_num_queries(0):
        assert get_object_permissions(rando, model, [obj.pk], codenames=[]) == {obj.pk: set()}


@pytest.mark.parametrize('actor_kind', ['anonymous', 'superuser', 'global', 'action_flag'])
def test_bulk_bypass_permissions(actor_kind, inventory, rando, global_inv_rd):
    actor = rando
    rando.is_platform_auditor = False
    if actor_kind == 'anonymous':
        actor = AnonymousUser()
    elif actor_kind == 'superuser':
        rando.is_superuser = True
    elif actor_kind == 'global':
        global_inv_rd.give_global_permission(rando)
    else:
        rando.is_platform_auditor = True
    with override_settings(ANSIBLE_BASE_BYPASS_ACTION_FLAGS={'view_inventory': 'is_platform_auditor'}):
        permissions = get_object_permissions(actor, Inventory, [inventory.pk])
        assert permissions == {inventory.pk: set()}
        if actor_kind != 'anonymous':
            assert actor.has_obj_perm(inventory, 'view')
            assert actor.has_obj_perm(inventory, 'change') == (actor_kind in ('superuser', 'global'))


def test_bulk_permissions_are_per_actor(inventory, rando, inv_rd):
    from django.contrib.auth import get_user_model

    other_user = get_user_model().objects.create(username='other')
    inv_rd.give_permission(rando, inventory)
    assert get_object_permissions(rando, Inventory, [inventory.pk]) == {inventory.pk: {'view_inventory', 'change_inventory'}}
    assert get_object_permissions(other_user, Inventory, [inventory.pk]) == {inventory.pk: set()}
    assert not other_user.has_obj_perm(inventory, 'change')


def test_bulk_permissions_do_not_change_normal_evaluation(inventory, rando, inv_rd, organization):
    before = get_object_permissions(rando, Inventory, [inventory.pk])
    inv_rd.give_permission(rando, inventory)
    assert before[inventory.pk] == set()
    assert rando.has_obj_perm(inventory, 'change')
    after = get_object_permissions(rando, Inventory, [inventory.pk])
    assert 'change_inventory' in after[inventory.pk]

    new_inventory = Inventory.objects.create(organization=organization)
    inv_rd.give_permission(rando, new_inventory)
    assert rando.has_obj_perm(new_inventory, 'change')
    inv_rd.remove_permission(rando, inventory)
    assert not rando.has_obj_perm(inventory, 'change')
