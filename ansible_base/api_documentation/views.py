from collections import OrderedDict

from rest_framework import permissions
from rest_framework.response import Response

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView


class DocsRootView(AnsibleBaseDjangoAppApiView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, format=None):
        '''Index of API documentation endpoints'''
        data = OrderedDict()
        data['swagger'] = get_relative_url('swagger-ui')
        data['redoc'] = get_relative_url('redoc')
        data['schema'] = get_relative_url('schema')
        return Response(data)
