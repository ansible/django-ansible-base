from unittest.mock import MagicMock

import pytest
from rest_framework.serializers import ValidationError

from ansible_base.authentication.serializers.authenticator_map import AuthenticatorMapSerializer
from ansible_base.lib.utils.auth import get_organization_model, get_team_model


@pytest.fixture
def serializer():
    return AuthenticatorMapSerializer()


@pytest.fixture
def team_role():
    role = MagicMock()
    content_type = MagicMock()
    role.content_type = content_type
    content_type.model_class = MagicMock(return_value=get_team_model())
    return role


@pytest.fixture
def organization_role():
    role = MagicMock()
    content_type = MagicMock()
    role.content_type = content_type
    content_type.model_class = MagicMock(return_value=get_organization_model())
    return role


@pytest.fixture
def system_role():
    role = MagicMock()
    role.content_type = None
    return role


class TestAuthenticatorMapSerializerMapType:
    @pytest.fixture(autouse=True)
    def init_serializer(self, serializer):
        serializer.validate_trigger_data = MagicMock(return_value={})
        serializer.validate_role_data = MagicMock(return_value={})

    def test_validate_map_type_organization(self, serializer, system_role):
        """map_type='organization' requires fields organization and role"""
        with pytest.raises(ValidationError) as e:
            serializer.validate(dict(name="authentication_map_1", map_type="organization"))
        assert set(e.value.detail.keys()) == {'organization', 'role'}

        with pytest.raises(ValidationError) as e:
            serializer.validate(dict(name="authentication_map_1", map_type="organization", organization='test_org'))
        assert list(e.value.detail.keys()) == ['role']

        serializer.validate(dict(name="authentication_map_1", map_type="organization", organization='test_org', role=system_role))

    def test_validate_map_type_team(self, serializer, system_role):
        """map_type='team' requires fields organization, team and role"""
        with pytest.raises(ValidationError) as e:
            serializer.validate(dict(name="authentication_map_1", map_type="team"))
        assert set(e.value.detail.keys()) == {'organization', 'team', 'role'}

        serializer.validate(dict(name="authentication_map_1", map_type="team", team='test_team', organization='test_org', role=system_role))

    def test_validate_map_type_role(self, serializer, system_role):
        """map_type='role' requires field role"""
        with pytest.raises(ValidationError) as e:
            serializer.validate(dict(name="authentication_map_1", map_type="role"))
        assert list(e.value.detail.keys()) == ['role']

        serializer.validate(dict(name="authentication_map_1", map_type="role", role=system_role))

    @pytest.mark.parametrize('map_type', ['is_superuser', 'allow'])
    def test_validate_map_type_others(self, map_type, serializer, system_role):
        """map_type='is_superuser' or 'allow' can't have field role"""
        serializer.validate(dict(name="authentication_map_1", map_type=map_type))
        serializer.validate(dict(name="authentication_map_1", map_type=map_type, organization='test_org', team='test_team'))

        with pytest.raises(ValidationError) as e:
            serializer.validate(dict(name="authentication_map_1", map_type=map_type, role=system_role))
        assert list(e.value.detail.keys()) == ['role']


class TestAuthenticatorMapSerializerRole:
    @pytest.fixture(autouse=True)
    def init_serializer(self, serializer):
        serializer.validate_trigger_data = MagicMock(return_value={})

    def test_validate_role_system_role(self, serializer, system_role):
        try:
            serializer.validate(dict(name="authentication_map_1", map_type="role", role=system_role))
            serializer.validate(dict(name="authentication_map_1", map_type="role", role=system_role, organization='test_org'))
            serializer.validate(dict(name="authentication_map_1", map_type="role", role=system_role, team='test_team'))
        except ValidationError as e:
            pytest.fail(f"Validation should pass, but: {str(e)}")

    def test_validate_role_team_role(self, serializer, team_role):
        with pytest.raises(ValidationError) as e:
            serializer.validate(dict(name="authentication_map_1", map_type="role", role=team_role))
        assert set(e.value.detail.keys()) == {'organization', 'team'}

        with pytest.raises(ValidationError) as e:
            serializer.validate(dict(name="authentication_map_1", map_type="role", role=team_role, organization='test_org'))
        assert str(e.value) == "{'team': ErrorDetail(string='You must specify a team with the selected role', code='invalid')}"

        try:
            serializer.validate(dict(name="authentication_map_1", map_type="role", role=team_role, organization='test_org', team='test_team'))
        except ValidationError as e:
            pytest.fail(f"Validation should pass, but: {str(e)}")

    def test_validate_role_organization_role(self, serializer, organization_role):
        with pytest.raises(ValidationError) as e:
            serializer.validate(dict(name="authentication_map_1", map_type="role", role=organization_role))
        assert str(e.value) == "{'organization': ErrorDetail(string='You must specify an organization with the selected role', code='invalid')}"

        try:
            serializer.validate(dict(name="authentication_map_1", map_type="role", role=organization_role, organization='test_org'))
        except ValidationError as e:
            pytest.fail(f"Validation should pass, but: {str(e)}")
