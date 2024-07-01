from collections import OrderedDict

from django.utils.translation import gettext_lazy as _
from rest_framework import permissions
from rest_framework.response import Response

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView


class ApiOAuthAuthorizationRootView(AnsibleBaseDjangoAppApiView):
    permission_classes = (permissions.AllowAny,)
    name = _("API OAuth 2 Authorization Root")
    versioning_class = None
    swagger_topic = 'Authentication'

    def get(self, request, format=None):
        data = OrderedDict()
        data['authorize'] = get_relative_url('authorize')
        data['revoke_token'] = get_relative_url('revoke-token')
        data['token'] = get_relative_url('token')
        return Response(data)
