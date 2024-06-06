from unittest.mock import MagicMock

import pytest
from rest_framework.serializers import ValidationError

from ansible_base.authentication.serializers.authenticator_map import AuthenticatorMapSerializer
from test_app.tests.authentication.conftest import ORG_MEMBER_ROLE_NAME, SYSTEM_ROLE_NAME, TEAM_MEMBER_ROLE_NAME


@pytest.fixture
def serializer():
    return AuthenticatorMapSerializer()


class TestAuthenticatorMapSerializerMapType:
    @pytest.fixture(autouse=True)
    def init_serializer(self, serializer):
        serializer.validate_trigger_data = MagicMock(return_value={})
        serializer.validate_role_data = MagicMock(return_value={})
        serializer._is_rbac_installed = MagicMock(return_value=True)

    def test_validate_map_type_organization(self, serializer):
        """map_type='organization' requires fields organization and role"""
        with pytest.raises(ValidationError) as e:
            serializer.validate(dict(name="authentication_map_1", map_type="organization"))
        assert set(e.value.detail.keys()) == {'organization', 'role'}

        with pytest.raises(ValidationError) as e:
            serializer.validate(dict(name="authentication_map_1", map_type="organization", organization='test_org'))
        assert list(e.value.detail.keys()) == ['role']

        serializer.validate(dict(name="authentication_map_1", map_type="organization", organization='test_org', role=SYSTEM_ROLE_NAME))

    def test_validate_map_type_team(self, serializer):
        """map_type='team' requires fields organization, team and role"""
        with pytest.raises(ValidationError) as e:
            serializer.validate(dict(name="authentication_map_1", map_type="team"))
        assert set(e.value.detail.keys()) == {'organization', 'team', 'role'}

        serializer.validate(dict(name="authentication_map_1", map_type="team", team='test_team', organization='test_org', role=SYSTEM_ROLE_NAME))

    def test_validate_map_type_role(self, serializer):
        """map_type='role' requires field role"""
        with pytest.raises(ValidationError) as e:
            serializer.validate(dict(name="authentication_map_1", map_type="role"))
        assert list(e.value.detail.keys()) == ['role']

        serializer.validate(dict(name="authentication_map_1", map_type="role", role=SYSTEM_ROLE_NAME))

    @pytest.mark.parametrize('map_type', ['is_superuser', 'allow'])
    def test_validate_map_type_others(self, map_type, serializer):
        """map_type='is_superuser' or 'allow' can't have field role"""
        serializer.validate(dict(name="authentication_map_1", map_type=map_type))
        serializer.validate(dict(name="authentication_map_1", map_type=map_type, organization='test_org', team='test_team'))

        with pytest.raises(ValidationError) as e:
            serializer.validate(dict(name="authentication_map_1", map_type=map_type, role=SYSTEM_ROLE_NAME))
        assert list(e.value.detail.keys()) == ['role']


@pytest.mark.django_db
class TestAuthenticatorMapSerializerRole:
    @pytest.fixture(autouse=True)
    def init_serializer(self, serializer):
        serializer.validate_trigger_data = MagicMock(return_value={})
        serializer._is_rbac_installed = MagicMock(return_value=True)

    def test_validate_role_system_role(self, serializer, system_role):
        try:
            serializer.validate(dict(name="authentication_map_1", map_type="role", role=SYSTEM_ROLE_NAME))
            serializer.validate(dict(name="authentication_map_2", map_type="role", role=SYSTEM_ROLE_NAME, organization='test_org'))
            serializer.validate(dict(name="authentication_map_3", map_type="role", role=SYSTEM_ROLE_NAME, team='test_team'))
        except ValidationError as e:
            pytest.fail(f"Validation should pass, but: {str(e)}")

        with pytest.raises(ValidationError) as e:
            serializer.validate(dict(name="authentication_map_4", map_type="team", role=SYSTEM_ROLE_NAME, organization='test_org', team='test_team'))
        assert str(e.value) == "{'role': ErrorDetail(string='For a team map type you must specify a team based role', code='invalid')}"

        with pytest.raises(ValidationError) as e:
            serializer.validate(dict(name="authentication_map_5", map_type="organization", role=SYSTEM_ROLE_NAME, organization='test_org'))
        assert str(e.value) == "{'role': ErrorDetail(string='For an organization map type you must specify an organization based role', code='invalid')}"

    def test_validate_role_team_role(self, serializer, member_rd):
        with pytest.raises(ValidationError) as e:
            serializer.validate(dict(name="authentication_map_1", map_type="role", role=TEAM_MEMBER_ROLE_NAME))
        assert set(e.value.detail.keys()) == {'organization', 'team'}

        with pytest.raises(ValidationError) as e:
            serializer.validate(dict(name="authentication_map_2", map_type="role", role=TEAM_MEMBER_ROLE_NAME, organization='test_org'))
        assert str(e.value) == "{'team': ErrorDetail(string='You must specify a team with the selected role', code='invalid')}"

        try:
            serializer.validate(dict(name="authentication_map_3", map_type="role", role=TEAM_MEMBER_ROLE_NAME, organization='test_org', team='test_team'))
        except ValidationError as e:
            pytest.fail(f"Validation should pass, but: {str(e)}")

        try:
            serializer.validate(dict(name="authentication_map_4", map_type="team", role=TEAM_MEMBER_ROLE_NAME, organization='test_org', team='test_team'))
        except ValidationError as e:
            pytest.fail(f"Validation should pass, but: {str(e)}")

        with pytest.raises(ValidationError) as e:
            serializer.validate(
                dict(name="authentication_map_5", map_type="organization", role=TEAM_MEMBER_ROLE_NAME, organization='test_org', team='test_team')
            )
        assert str(e.value) == "{'role': ErrorDetail(string='For an organization map type you must specify an organization based role', code='invalid')}"

    def test_validate_role_organization_role(self, serializer, org_member_rd):
        with pytest.raises(ValidationError) as e:
            serializer.validate(dict(name="authentication_map_1", map_type="role", role=ORG_MEMBER_ROLE_NAME))
        assert str(e.value) == "{'organization': ErrorDetail(string='You must specify an organization with the selected role', code='invalid')}"

        try:
            serializer.validate(dict(name="authentication_map_2", map_type="role", role=ORG_MEMBER_ROLE_NAME, organization='test_org'))
        except ValidationError as e:
            pytest.fail(f"Validation should pass, but: {str(e)}")

        with pytest.raises(ValidationError) as e:
            serializer.validate(dict(name="authentication_map_3", map_type="team", role=ORG_MEMBER_ROLE_NAME, organization='test_org', team='test_team'))
        assert str(e.value) == "{'role': ErrorDetail(string='For a team map type you must specify a team based role', code='invalid')}"

        try:
            serializer.validate(
                dict(name="authentication_map_4", map_type="organization", role=ORG_MEMBER_ROLE_NAME, organization='test_org', team='test_team')
            )
        except ValidationError as e:
            pytest.fail(f"Validation should pass, but: {str(e)}")
