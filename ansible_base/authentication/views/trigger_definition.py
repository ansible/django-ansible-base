from rest_framework.response import Response

from ansible_base.authentication.utils.trigger_definition import TRIGGER_DEFINITION
from ansible_base.lib.utils.views import AnsibleBaseDjanoAppApiView


class TriggerDefinitionView(AnsibleBaseDjanoAppApiView):
    def get(self, request, format=None):
        return Response(TRIGGER_DEFINITION)
