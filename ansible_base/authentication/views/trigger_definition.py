from rest_framework.response import Response

from ansible_base.authentication.utils.trigger_definition import TRIGGER_DEFINITION
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView


class TriggerDefinitionView(AnsibleBaseDjangoAppApiView):
    def get(self, request, format=None):
        return Response(TRIGGER_DEFINITION)
