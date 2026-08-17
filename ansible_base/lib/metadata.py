from rest_framework import serializers
from rest_framework.metadata import SimpleMetadata


def inject_clean_text_patterns(field, field_info):
    """
    If the parent serializer uses CleanTextMixin, inject validation
    pattern metadata into the field info dict for OPTIONS responses.

    Tier 1 (name fields): exposes the allowlist pattern and description.
    Tier 2 (other text fields): exposes the blocklist pattern and description.

    Safe to call on any field — returns field_info unmodified when
    CleanTextMixin is not in the serializer's MRO or the field is not
    a text field subject to validation.
    """
    from ansible_base.lib.serializers.mixins import CleanTextMixin
    from ansible_base.lib.utils.validation import DANGEROUS_PATTERNS, RESOURCE_NAME_RE

    serializer = field.parent
    if not isinstance(serializer, CleanTextMixin):
        return field_info

    if not isinstance(field, serializers.CharField):
        return field_info

    if field.field_name in getattr(serializer, 'excluded_fields', frozenset()):
        return field_info

    if field.field_name in serializer.name_fields:
        field_info['pattern'] = RESOURCE_NAME_RE.pattern.replace(r'\Z', '$')
        field_info['pattern_description'] = 'May only contain letters, numbers, spaces, hyphens, underscores, dots, and @. Must start with a letter, number, or underscore. Maximum 512 characters.'
    else:
        field_info['blocked_pattern'] = DANGEROUS_PATTERNS.pattern
        field_info['blocked_pattern_flags'] = 'i' if DANGEROUS_PATTERNS.flags & 2 else ''
        field_info['blocked_pattern_description'] = "Must not contain HTML tags, script markup, unsafe URI schemes (javascript:, vbscript:, data:), shell interpolation syntax, template expressions, or control characters."

    return field_info


class CleanTextMetadata(SimpleMetadata):
    """
    Extends SimpleMetadata to expose CleanTextMixin validation patterns
    in OPTIONS responses. Drop-in replacement for services that don't
    define their own metadata class.
    """

    def get_field_info(self, field):
        field_info = super().get_field_info(field)
        return inject_clean_text_patterns(field, field_info)
