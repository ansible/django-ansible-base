from rest_framework import serializers as drf_serializers
from rest_framework.response import Response

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_class, get_authenticator_plugins
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView


def _inject_validation_patterns(config_schema, config, encrypted_fields):
    from ansible_base.lib.metadata import get_tier2_pattern, validation_enabled

    if not validation_enabled():
        return

    tier2 = get_tier2_pattern()
    fields = config.get_fields()

    for entry in config_schema:
        field_name = entry['name']
        if field_name in encrypted_fields:
            continue
        field = fields.get(field_name)
        if field and isinstance(field, drf_serializers.CharField):
            entry['pattern'] = tier2['pattern']
            entry['patternDescription'] = tier2['description']
            entry['flags'] = tier2['flags']


class AuthenticatorPluginView(AnsibleBaseDjangoAppApiView):
    def get(self, request, format=None):
        plugins = get_authenticator_plugins()
        resp = {"authenticators": []}

        for p in plugins:
            try:
                klass = get_authenticator_class(p)
                config = klass.configuration_class()
                config_schema = config.get_configuration_schema()
                _inject_validation_patterns(config_schema, config, klass.configuration_encrypted_fields)
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
