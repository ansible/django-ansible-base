import pytest
from django.db.utils import IntegrityError

from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleEvaluation
from test_app.models import Organization


@pytest.mark.django_db
def test_role_definition_name_unique():
    RoleDefinition.objects.create(name='foo')
    with pytest.raises(IntegrityError):
        RoleDefinition.objects.create(name='foo')


@pytest.mark.django_db
def test_object_role_unique_rule():
    org = Organization.objects.create(name='foo')
    rd = RoleDefinition.objects.create(name='foo')
    ObjectRole.objects.create(object_id=org.id, content_type_id=permission_registry.org_ct_id, role_definition=rd)
    with pytest.raises(IntegrityError):
        ObjectRole.objects.create(object_id=org.id, content_type_id=permission_registry.org_ct_id, role_definition=rd)


@pytest.mark.django_db
def test_role_evaluation_unique_rule():
    org = Organization.objects.create(name='foo')
    rd = RoleDefinition.objects.create(name='foo')
    obj_role = ObjectRole.objects.create(role_definition=rd, object_id=org.id, content_type_id=permission_registry.org_ct_id)
    RoleEvaluation.objects.create(codename='view_organization', role=obj_role, object_id=org.id, content_type_id=permission_registry.org_ct_id)
    with pytest.raises(IntegrityError):
        RoleEvaluation.objects.create(codename='view_organization', role=obj_role, object_id=org.id, content_type_id=permission_registry.org_ct_id)
