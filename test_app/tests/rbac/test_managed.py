import pytest
from django.apps import apps

from ansible_base.rbac import permission_registry
from ansible_base.rbac.managed import ManagedReadOnlyBase, get_managed_role_constructors, managed_role_templates
from ansible_base.rbac.models import DABPermission, RoleDefinition
from ansible_base.rbac.validators import validate_permissions_for_model


@pytest.mark.django_db
def test_courtesy_roles_pass_validation():
    """Because these use migration apps, we can not use normal model code, so we validate in tests"""
    for template_name, cls in managed_role_templates.items():
        if '_base' in template_name:
            continue  # abstract, not intended to be used
        constructor = cls()
        perm_list = []
        for str_perm in constructor.get_permissions(apps):
            if '.' in str_perm:
                perm_list.append(DABPermission.objects.get(api_slug=str_perm))
            else:
                perm_list.append(DABPermission.objects.get(codename=str_perm))
        model_cls = constructor.get_model(apps)
        if model_cls is not None:
            ct = permission_registry.content_type_model.objects.get_for_model(constructor.get_model(apps))
        else:
            ct = None  # system role
        validate_permissions_for_model(perm_list, ct, managed=True)


@pytest.mark.django_db
def test_cow_admin():
    rd = RoleDefinition.objects.managed.cow_admin
    perm_list = [perm.codename for perm in rd.permissions.all()]
    assert set(perm_list) == {'change_cow', 'view_cow', 'delete_cow', 'say_cow'}


@pytest.mark.django_db
def test_cow_mooer():
    rd = RoleDefinition.objects.managed.cow_moo
    perm_list = [perm.codename for perm in rd.permissions.all()]
    assert set(perm_list) == {'view_cow', 'say_cow'}
    assert rd.name == 'Cow Mooer'


@pytest.mark.django_db
def test_create_all_managed_roles():
    "This is a method that may be called in migrations, etc."
    assert not RoleDefinition.objects.filter(name='Cow Mooer').exists()
    permission_registry.create_managed_roles(apps)


def test_read_only_base_is_registered_as_shortname():
    """read_only_base must be usable as a shortname in ANSIBLE_BASE_MANAGED_ROLE_REGISTRY."""
    assert 'read_only_base' in managed_role_templates
    assert managed_role_templates['read_only_base'] is ManagedReadOnlyBase


@pytest.mark.django_db
def test_read_only_base_shortname_creates_view_only_role():
    """A consuming app can declare a read-only managed role via the registry shortname."""
    registry_entry = {
        'my_viewer': {
            'shortname': 'read_only_base',
            'name': 'Cow Viewer',
            'model_name': 'test_app.Cow',
        }
    }
    constructors = get_managed_role_constructors(apps, registry_entry)
    assert 'my_viewer' in constructors

    constructor = constructors['my_viewer']
    assert constructor.name == 'Cow Viewer'
    assert isinstance(constructor, ManagedReadOnlyBase)

    perms = constructor.get_permissions(apps)
    assert all('.view' in p for p in perms), f"Expected only view permissions, got: {perms}"
    assert any('view_cow' in p for p in perms)
