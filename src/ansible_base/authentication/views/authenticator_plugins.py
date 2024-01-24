from rest_framework.response import Response
from rest_framework.views import APIView

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_class, get_authenticator_plugins


class AuthenticatorPluginView(APIView):
    def get(self, request, format=None):
        plugins = get_authenticator_plugins()
        resp = {"authenticators": []}

        for p in plugins:
            try:
                klass = get_authenticator_class(p)
                config = klass.configuration_class()
                config_schema = config.get_configuration_schema()
                resp['authenticators'].append(
                    {"type": p, "configuration_schema": config_schema, "documentation_url": getattr(config, "documentation_url", None)}
                )
            except ImportError as ie:
                # If we got an import error its already logged and we can move on
                if 'errors' not in resp:
                    resp['errors'] = []
                resp['errors'].append(ie.__str__())

        resp['authenticators'] = sorted(resp['authenticators'], key=lambda k: k['type'])

        return Response(resp)
