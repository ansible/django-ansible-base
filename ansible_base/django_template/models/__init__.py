# User must be imported first or else we end up with a circular import
from ansible_base.django_template.models.user import AbstractTemplateUser  # noqa: 401  # isort: skip
from ansible_base.django_template.models.organization import AbstractTemplateOrganization  # noqa: 401  # isort: skip
from ansible_base.django_template.models.team import AbstractTemplateTeam  # noqa: 401  # isort: skip

from ansible_base.lib.utils.auth import get_organization_model, get_team_model
from ansible_base.rbac import permission_registry

if get_team_model(return_none_on_error=True) is not None:
    permission_registry.register(get_team_model(), parent_field_name='organization')
if get_organization_model(return_none_on_error=True) is not None:
    permission_registry.register(get_organization_model(), parent_field_name=None)
