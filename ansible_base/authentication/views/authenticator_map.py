from rest_framework.viewsets import ModelViewSet

from ansible_base.authentication.models import AuthenticatorMap
from ansible_base.authentication.serializers import AuthenticatorMapSerializer
from ansible_base.lib.metadata import (
    TIER2_PATTERN_DESCRIPTION,
    CleanTextMetadata,
    build_tier2_frontend_pattern,
    validation_enabled,
)
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView

# Fields the frontend renders per-trigger-attribute (attributes.{index}.attribute and
# attributes.{index}.value). The UI resolves OPTIONS metadata by the last path segment,
# so top-level ``attribute``/``value`` entries are applied to the nested inputs.
_TRIGGER_ATTRIBUTE_FIELD_NAMES = ('attribute', 'value')


class AuthenticatorMapMetadata(CleanTextMetadata):
    """OPTIONS metadata that also exposes Tier 2 patterns for nested trigger fields.

    ``inject_clean_text_patterns`` only decorates flat CharField/TextField serializer
    fields, so it skips the ``triggers`` JSONField entirely. As a result the Attribute
    and Value inputs under "Based on attributes" get no client-side validation metadata.
    The server already enforces Tier 2 (free text) validation on those attribute names
    and values, so inject the matching ``attribute``/``value`` hints into each OPTIONS
    action to let the frontend validate them before submit. See AAP-98256.
    """

    @staticmethod
    def _tier2_field_info(label):
        return {
            'type': 'string',
            'required': False,
            'read_only': False,
            'label': label,
            'pattern': build_tier2_frontend_pattern(),
            'patternDescription': TIER2_PATTERN_DESCRIPTION,
            'flags': 'i',
        }

    def determine_actions(self, request, view):
        actions = super().determine_actions(request, view)
        if not validation_enabled():
            return actions
        # Inject on create (POST) only. On update, AuthenticatorMapSerializer
        # grandfathers attribute names that are already stored on the map, so a
        # name predating validation stays valid as long as it is unchanged. A
        # static OPTIONS pattern can't express that per-instance exception, so
        # applying it to the PUT action would wrongly block edits to maps that
        # still carry a legacy name. Newly entered names remain enforced
        # server-side on update. See AAP-98256.
        post_action = actions.get('POST')
        if post_action is None:
            return actions
        # Don't clobber real serializer fields if one ever gains these names.
        for name in _TRIGGER_ATTRIBUTE_FIELD_NAMES:
            post_action.setdefault(name, self._tier2_field_info(name.capitalize()))
        return actions


class AuthenticatorMapViewSet(AnsibleBaseDjangoAppApiView, ModelViewSet):
    """
    API endpoint that allows authenticator maps to be viewed or edited.
    """

    resource_purpose = "conditional rule for granting access, membership or roles based on user attributes or groups"

    queryset = AuthenticatorMap.objects.all().order_by("id")
    serializer_class = AuthenticatorMapSerializer
    metadata_class = AuthenticatorMapMetadata
    allow_service_token = True
