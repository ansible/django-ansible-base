import logging

from rest_framework.response import Response
from rest_framework.views import APIView

from ansible_base.utils.authentication import generate_ui_auth_data

logger = logging.getLogger('ansible_base.views.ui_auth')


class UIAuth(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, format=None):
        response = generate_ui_auth_data()

        return Response(response)
