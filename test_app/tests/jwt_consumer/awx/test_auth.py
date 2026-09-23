from unittest import mock

import pytest

from ansible_base.jwt_consumer.awx.auth import AwxJWTAuthentication
from ansible_base.rbac.claims import save_user_claims
from ansible_base.resource_registry.models import Resource


def test_awx_process_permissions(user, caplog):
    authentication = AwxJWTAuthentication()
    assert authentication.use_rbac_permissions is True


def _build_claims(orgs, teams):
    """Build a claims dict from org/team model instances."""
    objects = {"organization": [], "team": []}
    object_roles = {}

    org_indexes = []
    for i, org in enumerate(orgs):
        objects["organization"].append(
            {
                "ansible_id": str(org.resource.ansible_id),
                "name": org.name,
            }
        )
        org_indexes.append(i)

    team_indexes = []
    for i, team in enumerate(teams):
        org_idx = next(j for j, o in enumerate(orgs) if o.pk == team.organization_id)
        objects["team"].append(
            {
                "ansible_id": str(team.resource.ansible_id),
                "name": team.name,
                "org": org_idx,
            }
        )
        team_indexes.append(i)

    if org_indexes:
        object_roles["Organization Admin"] = {"content_type": "organization", "objects": org_indexes}
    if team_indexes:
        object_roles["Team Member"] = {"content_type": "team", "objects": team_indexes}

    return {"objects": objects, "object_roles": object_roles, "global_roles": []}


# Hardcoded from awx/main/models/rbac.py
AWX_ROLE_DEFINITION_TO_ROLE_FIELD = {
    'Organization Member': 'member_role',
    'WorkflowJobTemplate Admin': 'admin_role',
    'Organization WorkflowJobTemplate Admin': 'workflow_admin_role',
    'WorkflowJobTemplate Execute': 'execute_role',
    'WorkflowJobTemplate Approve': 'approval_role',
    'InstanceGroup Admin': 'admin_role',
    'InstanceGroup Use': 'use_role',
    'Organization ExecutionEnvironment Admin': 'execution_environment_admin_role',
    'Project Admin': 'admin_role',
    'Organization Project Admin': 'project_admin_role',
    'Project Use': 'use_role',
    'Project Update': 'update_role',
    'JobTemplate Admin': 'admin_role',
    'Organization JobTemplate Admin': 'job_template_admin_role',
    'JobTemplate Execute': 'execute_role',
    'Inventory Admin': 'admin_role',
    'Organization Inventory Admin': 'inventory_admin_role',
    'Inventory Use': 'use_role',
    'Inventory Adhoc': 'adhoc_role',
    'Inventory Update': 'update_role',
    'Organization NotificationTemplate Admin': 'notification_admin_role',
    'Credential Admin': 'admin_role',
    'Organization Credential Admin': 'credential_admin_role',
    'Credential Use': 'use_role',
    'Team Admin': 'admin_role',
    'Team Member': 'member_role',
    'Organization Admin': 'admin_role',
    'Organization Audit': 'auditor_role',
    'Organization Execute': 'execute_role',
    'Organization Approval': 'approval_role',
}


class FakeMembers:
    """Simulates a Role.members M2M manager."""

    def __init__(self):
        self._members = set()

    def add(self, user):
        self._members.add(user.pk)

    def remove(self, user):
        self._members.discard(user.pk)

    def __contains__(self, item):
        pk = item.pk if hasattr(item, 'pk') else item
        return pk in self._members


class FakeRole:
    """Simulates an old AWX Role instance with a role_field and members."""

    def __init__(self, pk, role_field):
        self.pk = pk
        self.role_field = role_field
        self.members = FakeMembers()


class FakeRoleQuerySet:
    """Simulates Role.objects.filter(...).exclude(...)."""

    def __init__(self, roles):
        self._roles = roles

    def filter(self, members=None, role_field__in=None):
        filtered = [r for r in self._roles if (members is None or members.pk in r.members) and (role_field__in is None or r.role_field in role_field__in)]
        return FakeRoleQuerySet(filtered)

    def exclude(self, pk__in=None):
        excluded = pk__in or set()
        return FakeRoleQuerySet([r for r in self._roles if r.pk not in excluded])

    def __iter__(self):
        return iter(self._roles)


class FakeResource:
    """Wraps a real Resource but returns a doctored content_object."""

    def __init__(self, real_resource, content_object_override):
        self.ansible_id = real_resource.ansible_id
        self._content_object = content_object_override

    @property
    def content_object(self):
        return self._content_object


@pytest.fixture
def mock_awx_rbac():
    """Patch AWX imports in _sync_old_rbac with fakes.

    Returns (attach_fake_role, all_roles, fake_role_cls, register_object).
    Call register_object(obj) for each model instance that should be findable
    by _build_resource_map — this ensures resource.content_object returns the
    same Python object (with fake roles attached).
    """
    all_roles = []
    role_counter = [0]
    object_registry = {}  # ansible_id -> obj with fake roles attached

    def attach_fake_role(obj, field_name):
        role_counter[0] += 1
        role = FakeRole(pk=role_counter[0], role_field=field_name)
        setattr(obj, field_name, role)
        all_roles.append(role)
        return role

    def register_object(obj):
        ansible_id = str(obj.resource.ansible_id)
        object_registry[ansible_id] = obj

    fake_role_cls = mock.MagicMock()
    fake_role_cls.objects = FakeRoleQuerySet(all_roles)

    mock_rbac = mock.MagicMock()
    mock_rbac.ROLE_DEFINITION_TO_ROLE_FIELD = AWX_ROLE_DEFINITION_TO_ROLE_FIELD
    mock_rbac.Role = fake_role_cls

    mock_signals = mock.MagicMock()
    mock_signals.disable_activity_stream = mock.MagicMock(return_value=mock.MagicMock(__enter__=mock.Mock(), __exit__=mock.Mock()))

    original_filter = Resource.objects.filter

    def patched_filter(**kwargs):
        if 'ansible_id__in' in kwargs:
            real_qs = original_filter(**kwargs)
            return [FakeResource(r, object_registry.get(str(r.ansible_id), r.content_object)) for r in real_qs]
        return original_filter(**kwargs)

    with mock.patch.dict(
        'sys.modules',
        {
            'awx': mock.MagicMock(),
            'awx.main': mock.MagicMock(),
            'awx.main.models': mock.MagicMock(),
            'awx.main.models.rbac': mock_rbac,
            'awx.main.signals': mock_signals,
        },
    ):
        with mock.patch.object(Resource.objects, 'filter', side_effect=patched_filter):
            yield attach_fake_role, all_roles, fake_role_cls, register_object


@pytest.mark.django_db
class TestSyncOldRbac:

    def test_sync_adds_members(self, admin_user, organization, team, org_admin_rd, member_rd, mock_awx_rbac):
        attach_fake_role, all_roles, fake_role_cls, register_object = mock_awx_rbac
        org_admin_role = attach_fake_role(organization, 'admin_role')
        team_member_role = attach_fake_role(team, 'member_role')
        register_object(organization)
        register_object(team)
        fake_role_cls.objects = FakeRoleQuerySet(all_roles)

        claims = _build_claims([organization], [team])
        save_user_claims(admin_user, **claims)

        auth = AwxJWTAuthentication()
        auth._sync_old_rbac(admin_user, claims["objects"], claims["object_roles"])

        assert admin_user in org_admin_role.members
        assert admin_user in team_member_role.members

    def test_sync_removes_stale_members(self, admin_user, organization, team, org_admin_rd, member_rd, mock_awx_rbac):
        attach_fake_role, all_roles, fake_role_cls, register_object = mock_awx_rbac
        org_admin_role = attach_fake_role(organization, 'admin_role')
        team_member_role = attach_fake_role(team, 'member_role')
        register_object(organization)
        register_object(team)
        fake_role_cls.objects = FakeRoleQuerySet(all_roles)

        claims_full = _build_claims([organization], [team])
        save_user_claims(admin_user, **claims_full)
        auth = AwxJWTAuthentication()
        auth._sync_old_rbac(admin_user, claims_full["objects"], claims_full["object_roles"])

        assert admin_user in org_admin_role.members
        assert admin_user in team_member_role.members

        claims_reduced = _build_claims([organization], [])
        save_user_claims(admin_user, **claims_reduced)
        auth._sync_old_rbac(admin_user, claims_reduced["objects"], claims_reduced["object_roles"])

        assert admin_user in org_admin_role.members
        assert admin_user not in team_member_role.members

    def test_sync_skips_unknown_role_names(self, admin_user, organization, org_admin_rd, mock_awx_rbac):
        attach_fake_role, all_roles, fake_role_cls, register_object = mock_awx_rbac
        fake_role_cls.objects = FakeRoleQuerySet(all_roles)

        objects = {"organization": [{"ansible_id": str(organization.resource.ansible_id), "name": organization.name}]}
        object_roles = {"Bogus Role": {"content_type": "organization", "objects": [0]}}

        auth = AwxJWTAuthentication()
        auth._sync_old_rbac(admin_user, objects, object_roles)

    def test_sync_noop_without_awx(self, admin_user):
        """Without AWX installed, _sync_old_rbac is a silent no-op."""
        auth = AwxJWTAuthentication()
        auth._sync_old_rbac(admin_user, {}, {})
