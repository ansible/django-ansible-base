import pytest
from django.test import override_settings


@pytest.mark.django_db
@override_settings(ANSIBLE_BASE_CACHE_PARENT_PERMISSIONS=False)
def test_parent_permissions_not_cached(rando, organization, org_inv_rd, inventory):
    org_inv_rd.give_permission(rando, organization)
    assert rando.has_obj_perm(inventory, 'change_inventory')
    assert not rando.has_obj_perm(organization, 'change_inventory')


@pytest.mark.django_db
@override_settings(ANSIBLE_BASE_CACHE_PARENT_PERMISSIONS=True)
def test_parent_permissions_cached(rando, organization, org_inv_rd, inventory):
    org_inv_rd.give_permission(rando, organization)
    assert rando.has_obj_perm(inventory, 'change_inventory')
    assert rando.has_obj_perm(organization, 'change_inventory')
