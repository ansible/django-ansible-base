from functools import lru_cache

from rest_framework import serializers
from rest_framework.metadata import SimpleMetadata

_HTML_TAG_APPROX = r'<[a-zA-Z/!][^>]*>'


def _wrap_alternation(pattern):
    if '|' in pattern:
        return f'(?:{pattern})'
    return pattern


@lru_cache(maxsize=1)
def build_tier1_frontend_pattern():
    from ansible_base.lib.utils.validation import _ZALGO_RE, RESOURCE_NAME_PATTERN

    base = RESOURCE_NAME_PATTERN.replace(r'\Z', '$')
    deny_patterns = [_ZALGO_RE.pattern]
    lookaheads = ''.join(f'(?!.*{_wrap_alternation(p)})' for p in deny_patterns)
    return f'^{lookaheads}{base[1:]}'


@lru_cache(maxsize=1)
def build_tier2_frontend_pattern():
    from ansible_base.lib.utils.validation import _HANDLER_URI_RE, _INJECTION_RE, CONTROL_CHARS

    deny_patterns = [
        CONTROL_CHARS,
        _HTML_TAG_APPROX,
        _HANDLER_URI_RE.pattern,
        _INJECTION_RE.pattern,
    ]
    lookaheads = ''.join(f'(?!.*{_wrap_alternation(p)})' for p in deny_patterns)
    return f'^{lookaheads}[\\s\\S]*$'


def inject_clean_text_patterns(field, field_info):
    from ansible_base.lib.serializers.mixins import CleanTextMixin
    from ansible_base.lib.utils.settings import get_setting

    if not get_setting('ENHANCED_INPUT_VALIDATION_ENABLED', False):
        return field_info

    serializer = field.parent
    if not isinstance(serializer, CleanTextMixin):
        return field_info

    if not isinstance(field, serializers.CharField):
        return field_info

    if field.field_name in getattr(serializer, 'excluded_fields', frozenset()):
        return field_info

    if field.field_name in serializer.name_fields:
        field_info['pattern'] = build_tier1_frontend_pattern()
        field_info['patternDescription'] = (
            'May only contain letters, numbers, spaces, hyphens, underscores, '
            'dots, and @. Must start with a letter, number, or underscore. '
            'Maximum 512 characters.'
        )
        field_info['flags'] = 'u'
        field_info['normalize'] = 'NFC'
    else:
        field_info['pattern'] = build_tier2_frontend_pattern()
        field_info['patternDescription'] = "This field can't include HTML tags, script markup, " "unsafe URI schemes, shell syntax, or control characters."
        field_info['flags'] = 'i'

    return field_info


class CleanTextMetadata(SimpleMetadata):
    def get_field_info(self, field):
        field_info = super().get_field_info(field)
        return inject_clean_text_patterns(field, field_info)
