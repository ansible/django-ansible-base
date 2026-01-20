from collections import OrderedDict

from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema
from flags.state import flag_enabled
from rest_framework import permissions
from rest_framework.response import Response

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView


@extend_schema(exclude=True)
class ApiOAuthAuthorizationRootView(AnsibleBaseDjangoAppApiView):
    permission_classes = (permissions.AllowAny,)
    name = _("API OAuth 2 Authorization Root")
    versioning_class = None
    swagger_topic = 'Authentication'

    def get(self, request, format=None):
        data = OrderedDict()
        data['authorize'] = get_relative_url('oauth2_provider:authorize')
        data['revoke_token'] = get_relative_url('oauth2_provider:revoke-token')
        data['token'] = get_relative_url('oauth2_provider:token')
        if flag_enabled("FEATURE_OIDC_WORKLOAD_IDENTITY_ENABLED"):
            data['oidc-connect-discovery-info'] = get_relative_url('oauth2_provider:oidc-connect-discovery-info')
            data['jwks-info'] = get_relative_url('oauth2_provider:jwks-info')
        return Response(data)
