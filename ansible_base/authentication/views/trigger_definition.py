from rest_framework.response import Response
from rest_framework.views import APIView

from ansible_base.authentication.utils.trigger_definition import TRIGGER_DEFINITION


class TriggerDefinitionView(APIView):
    def get(self, request, format=None):
        return Response(TRIGGER_DEFINITION)
