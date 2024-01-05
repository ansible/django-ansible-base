import pytest
from django.test.utils import override_settings

from ansible_base.models.rbac import RoleDefinition, RoleEvaluation


@pytest.mark.django_db
def test_create_inventory(rando, inventory):
    assert set(RoleEvaluation.get_permissions(rando, inventory)) == set()
    RoleDefinition.objects.give_creator_permissions(rando, inventory)
    assert set(perm_name.split('_', 1)[0] for perm_name in RoleEvaluation.get_permissions(rando, inventory)) == {'change', 'delete', 'view'}
    assert RoleDefinition.objects.filter(name='inventory-creator-permission').exists()


@pytest.mark.django_db
def test_custom_creation_perms(rando, inventory):
    # these settings would not let users delete what they create
    # which someone might want, you do you
    with override_settings(ROLE_CREATOR_DEFAULTS=['change', 'view']):
        RoleDefinition.objects.give_creator_permissions(rando, inventory)
        assert set(perm_name.split('_', 1)[0] for perm_name in RoleEvaluation.get_permissions(rando, inventory)) == {'change', 'view'}
