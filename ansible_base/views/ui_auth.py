import logging

from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from ansible_base.models import Authenticator

logger = logging.getLogger('ansible_base.views.ui_auth')


class UIAuth(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, format=None):
        authenticators = Authenticator.objects.filter(enabled=True)
        response = {'show_login_form': False, 'passwords': [], 'ssos': []}
        for authenticator in authenticators:
            if authenticator.category == 'password':
                response['show_login_form'] = True
                response['passwords'].append(
                    {
                        'name': authenticator.name,
                        'type': authenticator.type,
                    }
                )
            elif authenticator.category == 'sso':
                response['ssos'].append(
                    {
                        'name': authenticator.name,
                        'login_url': reverse('social:begin', kwargs={'backend': authenticator.slug}),
                        'type': authenticator.type,
                    }
                )
            else:
                logger.error(f"Don't know how to handle authenticator of type {authenticator.type}")
        return Response(response)
