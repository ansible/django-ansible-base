import pytest

from django.apps import apps

from ansible_base.rbac.managed import courtesy_registry
from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import DABPermission

from ansible_base.rbac.validators import validate_permissions_for_model


@pytest.mark.django_db
def test_courtesy_roles_pass_validation():
    """Because these use migration apps, we can not use normal model code, so we validate in tests"""
    for cls in courtesy_registry.values():
        rd = cls(apps)
        perm_list = [DABPermission.objects.get(codename=str_perm) for str_perm in rd.get_permissions()]
        model_cls = rd.get_model()
        if model_cls is not None:
            ct = permission_registry.content_type_model.objects.get_for_model(rd.get_model())
        else:
            ct = None  # system role
        validate_permissions_for_model(perm_list, ct, managed=True)
