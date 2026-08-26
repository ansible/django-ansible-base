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
    from ansible_base.lib.utils.validation import _ZALGO_INTERLEAVED_APPROX, _ZALGO_RE, RESOURCE_NAME_PATTERN

    base = RESOURCE_NAME_PATTERN.replace(r'\Z', '$')
    # _ZALGO_RE catches 5+ *consecutive* combining marks. _ZALGO_INTERLEAVED_APPROX
    # additionally catches marks interleaved with base characters, approximating (but
    # not exactly replicating) the server's _has_dense_combining_marks() sliding
    # window check -- see the comment on _ZALGO_INTERLEAVED_APPROX in validation.py
    # for the known gap. Both are best-effort client-side hints;
    # validate_resource_name() is the actual security boundary.
    deny_patterns = [_ZALGO_RE.pattern, _ZALGO_INTERLEAVED_APPROX]
    lookaheads = ''.join(f'(?!.*{_wrap_alternation(p)})' for p in deny_patterns)
    return f'^{lookaheads}{base[1:]}'


@lru_cache(maxsize=1)
def build_tier2_frontend_pattern():
    """Best-effort client-side approximation of validate_free_text().

    validate_free_text() decodes each value through up to 3 rounds of HTML-entity
    decoding, percent-decoding, and NFKC normalization (_decoded_variants), then
    checks every decoded variant with a real HTML parser (nh3, via _contains_markup)
    rather than a regex. That iterative decode-then-parse pipeline cannot be
    expressed as a single bounded, JS-compatible regex, so _HTML_TAG_APPROX below
    only matches literal, undecoded "<tag>" markup in the raw string.
    Entity-encoded ("&lt;script&gt;"), URL-encoded ("%3Cscript%3E"), or
    nested/double-encoded payloads will NOT trip this client-side pattern. They are
    still rejected server-side by validate_free_text(), which remains the actual
    security boundary -- this pattern is a UX nicety, not a validation guarantee.
    See test_tier2_pattern_does_not_catch_html_entity_encoded_payload for a pinned
    regression test documenting this known, intentional gap.
    """
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

    # SlugField and IPAddressField both subclass CharField in DRF, but their
    # underlying model columns (models.SlugField / models.GenericIPAddressField)
    # override get_internal_type() to return their own name, so they're deliberately
    # excluded from Tier 1/Tier 2 backend validation by CleanTextMixin._classify_fields()
    # (which keys off get_internal_type() rather than isinstance() for this exact
    # reason). Advertising a `pattern` here for them would tell the client to enforce
    # a rule the backend never actually applies to that field.
    #
    # URLField is deliberately NOT excluded here: models.URLField doesn't override
    # get_internal_type() (it inherits CharField's "CharField"), so
    # _classify_fields() DOES treat URLField-backed columns as free text and runs
    # validate_free_text() on them server-side -- the pattern hint is accurate.
    if isinstance(field, (serializers.SlugField, serializers.IPAddressField)):
        return field_info

    if not isinstance(field, serializers.CharField):
        return field_info

    if field.field_name in getattr(serializer, 'excluded_fields', frozenset()):
        return field_info

    if field.field_name in serializer.name_fields:
        field_info['pattern'] = build_tier1_frontend_pattern()
        field_info['patternDescription'] = (
            'Enter a valid name. Use letters, numbers, spaces, hyphens (-), '
            'underscores (_), dots (.), and @. Start with a letter, number, '
            'or underscore. Max 512 characters.'
        )
        field_info['flags'] = 'u'
        field_info['normalize'] = 'NFC'
    else:
        field_info['pattern'] = build_tier2_frontend_pattern()
        field_info['patternDescription'] = (
            "This field can't include HTML tags, script markup, unsafe URI schemes, "
            "shell or template syntax, or control characters."
        )
        field_info['flags'] = 'i'

    return field_info


class CleanTextMetadata(SimpleMetadata):
    def get_field_info(self, field):
        field_info = super().get_field_info(field)
        return inject_clean_text_patterns(field, field_info)
