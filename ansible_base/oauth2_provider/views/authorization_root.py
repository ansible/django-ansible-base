from collections import OrderedDict

from django.utils.translation import gettext_lazy as _
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.reverse import _reverse

from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView


class ApiOAuthAuthorizationRootView(AnsibleBaseDjangoAppApiView):
    permission_classes = (permissions.AllowAny,)
    name = _("API OAuth 2 Authorization Root")
    versioning_class = None
    swagger_topic = 'Authentication'

    def get(self, request, format=None):
        data = OrderedDict()
        data['authorize'] = _reverse('authorize')
        data['revoke_token'] = _reverse('revoke-token')
        data['token'] = _reverse('token')
        return Response(data)
