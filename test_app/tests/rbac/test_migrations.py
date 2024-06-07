import pytest
from django.apps import apps
from django.contrib.contenttypes.models import ContentType

from ansible_base.rbac.migrations._utils import give_permissions
from ansible_base.rbac.models import DABPermission, RoleTeamAssignment, RoleUserAssignment
from ansible_base.rbac.permission_registry import permission_registry
from test_app.models import Team, User


@pytest.mark.django_db
def test_give_permissions(organization, inventory, inv_rd):
    user = User.objects.create(username='user')
    team = Team.objects.create(name='ateam', organization=organization)
    give_permissions(apps, inv_rd, users=[user], teams=[team], object_id=inventory.id, content_type_id=ContentType.objects.get_for_model(inventory).id)
    assert RoleUserAssignment.objects.filter(user=user).exists()
    assert RoleTeamAssignment.objects.filter(team=team).exists()


@pytest.mark.django_db
def test_give_permissions_by_id(organization, inventory, inv_rd):
    team = Team.objects.create(name='ateam', organization=organization)
    give_permissions(apps, inv_rd, teams=[team.id], object_id=inventory.id, content_type_id=ContentType.objects.get_for_model(inventory).id)
    assert RoleTeamAssignment.objects.filter(team=team).exists()


@pytest.mark.django_db
def test_permission_migration():
    "These are expected to be created via a post_migrate signal just like auth.Permission"
    assert len(DABPermission.objects.order_by('content_type').values_list('content_type').distinct()) == len(permission_registry.all_registered_models)
