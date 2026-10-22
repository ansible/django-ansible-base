from rest_framework import serializers as drf_serializers
from rest_framework.response import Response

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_class, get_authenticator_plugins
from ansible_base.lib.schemas.clean_text_patterns import authenticator_plugin_field_schema
from ansible_base.lib.utils.schema import extend_schema_if_available
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


def _authenticator_plugins_response_schema():
    """OpenAPI response schema for GET authenticator_plugins.

    Declares optional CleanText pattern keys on configuration_schema entries so
    the documented contract matches runtime injection when
    ENHANCED_INPUT_VALIDATION_ENABLED is on.
    """
    field_schema = authenticator_plugin_field_schema()
    return {
        'type': 'object',
        'properties': {
            'authenticators': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'type': {'type': 'string'},
                        'documentation_url': {'type': 'string', 'nullable': True},
                        'configuration_schema': {
                            'type': 'array',
                            'items': field_schema,
                            'description': (
                                'Per-plugin configuration field catalog. When '
                                'ENHANCED_INPUT_VALIDATION_ENABLED is on, non-secret '
                                'CharField entries include optional pattern, '
                                'patternDescription, and flags (Tier 2; no normalize).'
                            ),
                        },
                    },
                },
            },
            'errors': {
                'type': 'array',
                'items': {'type': 'string'},
            },
        },
    }


class AuthenticatorPluginView(AnsibleBaseDjangoAppApiView):
    @extend_schema_if_available(
        operation_id='authenticator_plugins_list',
        responses={200: _authenticator_plugins_response_schema()},
    )
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
