from unittest.mock import Mock, patch

import pytest
import regex
from django.test import override_settings
from rest_framework import generics, permissions, serializers
from rest_framework.metadata import SimpleMetadata
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from ansible_base.lib.metadata import (
    _HTML_TAG_APPROX,
    TIER1_PATTERN_DESCRIPTION,
    TIER2_PATTERN_DESCRIPTION,
    CleanTextMetadata,
    _wrap_alternation,
    build_tier1_frontend_pattern,
    build_tier2_frontend_pattern,
    get_tier1_pattern,
    get_tier2_pattern,
    inject_clean_text_patterns,
    validation_enabled,
)
from ansible_base.lib.serializers.mixins import CleanTextMixin
from ansible_base.lib.utils.validation import _HANDLER_URI_RE, _INJECTION_RE, CONTROL_CHARS
from test_app.models import MetadataTestModel


@pytest.fixture(autouse=True)
def clear_pattern_caches():
    build_tier1_frontend_pattern.cache_clear()
    build_tier2_frontend_pattern.cache_clear()


# ---------------------------------------------------------------------------
# _wrap_alternation
# ---------------------------------------------------------------------------


def test_wrap_alternation_adds_group_when_pipe_present():
    assert _wrap_alternation('a|b') == '(?:a|b)'


def test_wrap_alternation_noop_without_pipe():
    assert _wrap_alternation('abc') == 'abc'


# ---------------------------------------------------------------------------
# build_tier1_frontend_pattern
# ---------------------------------------------------------------------------


def test_tier1_pattern_is_string():
    assert isinstance(build_tier1_frontend_pattern(), str)


def test_tier1_pattern_starts_with_caret_lookahead():
    pattern = build_tier1_frontend_pattern()
    assert pattern.startswith('^(?!.*')


def test_tier1_pattern_ends_with_dollar():
    pattern = build_tier1_frontend_pattern()
    assert pattern.endswith('$')
    assert r'\Z' not in pattern


def test_tier1_pattern_compiles_with_regex_module():
    pattern = build_tier1_frontend_pattern()
    compiled = regex.compile(pattern, regex.UNICODE)
    assert compiled is not None


# ---------------------------------------------------------------------------
# build_tier2_frontend_pattern
# ---------------------------------------------------------------------------


def test_tier2_pattern_is_string():
    assert isinstance(build_tier2_frontend_pattern(), str)


def test_tier2_pattern_contains_deny_substrings():
    pattern = build_tier2_frontend_pattern()
    assert _HTML_TAG_APPROX in pattern
    assert CONTROL_CHARS in pattern
    assert _HANDLER_URI_RE.pattern in pattern
    assert _INJECTION_RE.pattern in pattern


def test_tier2_pattern_ends_with_catch_all():
    pattern = build_tier2_frontend_pattern()
    assert pattern.endswith(r'[\s\S]*$')


def test_tier2_pattern_compiles():
    pattern = build_tier2_frontend_pattern()
    compiled = regex.compile(pattern, regex.IGNORECASE)
    assert compiled is not None


# ---------------------------------------------------------------------------
# inject_clean_text_patterns — guard clauses
# ---------------------------------------------------------------------------


def _make_field(field_name='description', is_charfield=True, serializer_cls=CleanTextMixin, field_cls=None, model_internal_type='CharField'):
    from rest_framework import serializers as drf_serializers

    if field_cls is None:
        field_cls = drf_serializers.CharField if is_charfield else drf_serializers.IntegerField
    field = Mock(spec=field_cls)
    field.field_name = field_name
    field.source = field_name

    serializer = Mock(spec=serializer_cls)
    serializer.name_fields = frozenset({'name', 'username', 'hostname'})
    serializer.excluded_fields = frozenset()

    # Mock the model field lookup that inject_clean_text_patterns now uses
    model_field = Mock()
    model_field.name = field_name
    model_field.get_internal_type.return_value = model_internal_type
    meta = Mock()
    meta.get_field.return_value = model_field
    model = Mock()
    model._meta = meta
    serializer.Meta = Mock()
    serializer.Meta.model = model

    field.parent = serializer

    return field


@patch('ansible_base.lib.metadata.get_setting', return_value=False)
def test_inject_returns_unmodified_when_feature_disabled(mock_setting):
    field = _make_field()
    field_info = {'type': 'string'}
    result = inject_clean_text_patterns(field, field_info)
    assert 'pattern' not in result


@patch('ansible_base.lib.metadata.get_setting', return_value=True)
def test_inject_returns_unmodified_for_non_cleantext_serializer(mock_setting):
    from rest_framework import serializers as drf_serializers

    field = Mock(spec=drf_serializers.CharField)
    field.field_name = 'description'
    field.source = 'description'
    field.parent = Mock(spec=drf_serializers.Serializer)
    field_info = {'type': 'string'}
    result = inject_clean_text_patterns(field, field_info)
    assert 'pattern' not in result


@patch('ansible_base.lib.metadata.get_setting', return_value=True)
def test_inject_returns_unmodified_for_non_charfield(mock_setting):
    field = _make_field(is_charfield=False, model_internal_type='IntegerField')
    field_info = {'type': 'integer'}
    result = inject_clean_text_patterns(field, field_info)
    assert 'pattern' not in result


@patch('ansible_base.lib.metadata.get_setting', return_value=True)
def test_inject_returns_unmodified_for_slugfield(mock_setting):
    # SlugField's model column overrides get_internal_type() to return 'SlugField',
    # so _classify_fields() excludes it from backend validation. The metadata layer
    # mirrors this via the same get_internal_type() check.
    field = _make_field(field_name='slug', field_cls=serializers.SlugField, model_internal_type='SlugField')
    field_info = {'type': 'string'}
    result = inject_clean_text_patterns(field, field_info)
    assert 'pattern' not in result


@patch('ansible_base.lib.metadata.get_setting', return_value=True)
def test_inject_applies_pattern_for_urlfield(mock_setting):
    # models.URLField does NOT override get_internal_type() -- it inherits
    # CharField's "CharField" -- so _classify_fields() treats it as free text
    # and validates it server-side. The metadata layer mirrors this.
    field = _make_field(field_name='homepage', field_cls=serializers.URLField, model_internal_type='CharField')
    field_info = {'type': 'string'}
    result = inject_clean_text_patterns(field, field_info)
    assert 'pattern' in result


@patch('ansible_base.lib.metadata.get_setting', return_value=True)
def test_inject_returns_unmodified_for_ipaddressfield(mock_setting):
    # GenericIPAddressField overrides get_internal_type() to return its own name,
    # so _classify_fields() excludes it from backend validation. The metadata
    # layer mirrors this via the same get_internal_type() check.
    field = _make_field(field_name='ip_address', field_cls=serializers.IPAddressField, model_internal_type='GenericIPAddressField')
    field_info = {'type': 'string'}
    result = inject_clean_text_patterns(field, field_info)
    assert 'pattern' not in result


@patch('ansible_base.lib.metadata.get_setting', return_value=True)
def test_inject_returns_unmodified_for_excluded_field(mock_setting):
    field = _make_field(field_name='template')
    field.parent.excluded_fields = frozenset({'template'})
    field_info = {'type': 'string'}
    result = inject_clean_text_patterns(field, field_info)
    assert 'pattern' not in result


@patch('ansible_base.lib.metadata.get_setting', return_value=True)
def test_inject_returns_unmodified_when_no_meta_model(mock_setting):
    """Serializers without Meta.model (e.g. plain Serializer subclasses) should
    silently skip pattern injection rather than raising an error."""
    field = _make_field(field_name='description')
    # Remove Meta.model so inject_clean_text_patterns takes the early-return path
    field.parent.Meta.model = None
    field_info = {'type': 'string'}
    result = inject_clean_text_patterns(field, field_info)
    assert 'pattern' not in result


@patch('ansible_base.lib.metadata.get_setting', return_value=True)
def test_inject_returns_unmodified_when_field_not_on_model(mock_setting):
    """Computed / method fields with no backing model column should be skipped."""
    from django.core.exceptions import FieldDoesNotExist

    field = _make_field(field_name='computed')
    field.parent.Meta.model._meta.get_field.side_effect = FieldDoesNotExist
    field_info = {'type': 'string'}
    result = inject_clean_text_patterns(field, field_info)
    assert 'pattern' not in result


# ---------------------------------------------------------------------------
# inject_clean_text_patterns — tier 1
# ---------------------------------------------------------------------------


@patch('ansible_base.lib.metadata.get_setting', return_value=True)
def test_inject_tier1_keys(mock_setting):
    field = _make_field(field_name='name')
    field_info = {'type': 'string'}
    result = inject_clean_text_patterns(field, field_info)

    assert 'pattern' in result
    assert 'patternDescription' in result
    assert result['flags'] == 'u'
    assert result['normalize'] == 'NFC'


@patch('ansible_base.lib.metadata.get_setting', return_value=True)
def test_inject_tier1_no_blocked_pattern_keys(mock_setting):
    field = _make_field(field_name='name')
    field_info = {'type': 'string'}
    result = inject_clean_text_patterns(field, field_info)
    blocked_keys = [k for k in result if k.startswith('blocked_pattern')]
    assert blocked_keys == []


@patch('ansible_base.lib.metadata.get_setting', return_value=True)
def test_inject_tier1_uses_camelcase(mock_setting):
    field = _make_field(field_name='name')
    field_info = {'type': 'string'}
    result = inject_clean_text_patterns(field, field_info)
    assert 'patternDescription' in result
    assert 'pattern_description' not in result


# ---------------------------------------------------------------------------
# inject_clean_text_patterns — aliased field regression
# ---------------------------------------------------------------------------


@patch('ansible_base.lib.metadata.get_setting', return_value=True)
def test_inject_uses_model_field_name_not_serializer_alias_for_tier_selection(mock_setting):
    """Regression test: when a serializer aliases a model field (field_name !=
    source), the tier selection must use the *model* field name (model_field.name),
    not the serializer field name (field.field_name).  Before the fix,
    inject_clean_text_patterns() checked ``field.field_name`` against name_fields
    and excluded_fields, so an alias like display_name -> name would get tier 2
    instead of tier 1."""
    field = _make_field(field_name='name')
    # Simulate a serializer alias: field_name='display_name' but source='name'
    # (the underlying model field).  _make_field already set model_field.name='name'.
    field.field_name = 'display_name'
    # field.source stays 'name', so the model field lookup returns
    # a model_field whose .name is 'name' — which IS in name_fields.

    field_info = {'type': 'string'}
    result = inject_clean_text_patterns(field, field_info)

    # Must be tier 1 (resource-name pattern), not tier 2
    assert 'pattern' in result
    assert result['flags'] == 'u', 'Expected tier 1 (flags=u) because model field name is in name_fields'
    assert result['normalize'] == 'NFC'
    assert result['patternDescription'] == TIER1_PATTERN_DESCRIPTION


@patch('ansible_base.lib.metadata.get_setting', return_value=True)
def test_inject_excluded_fields_uses_model_field_name_not_serializer_alias(mock_setting):
    """Regression test: excluded_fields check must also use the model field name,
    not the serializer alias."""
    field = _make_field(field_name='template')
    # Simulate alias: serializer calls it 'tmpl', model field is 'template'
    field.field_name = 'tmpl'
    # field.source stays 'template', model_field.name stays 'template'
    field.parent.excluded_fields = frozenset({'template'})

    field_info = {'type': 'string'}
    result = inject_clean_text_patterns(field, field_info)

    assert 'pattern' not in result, 'Field should be excluded by model field name, not serializer alias'


# ---------------------------------------------------------------------------
# inject_clean_text_patterns — tier 2
# ---------------------------------------------------------------------------


@patch('ansible_base.lib.metadata.get_setting', return_value=True)
def test_inject_tier2_keys(mock_setting):
    field = _make_field(field_name='description')
    field_info = {'type': 'string'}
    result = inject_clean_text_patterns(field, field_info)

    assert 'pattern' in result
    assert 'patternDescription' in result
    assert result['flags'] == 'i'


@patch('ansible_base.lib.metadata.get_setting', return_value=True)
def test_inject_tier2_no_normalize(mock_setting):
    field = _make_field(field_name='description')
    field_info = {'type': 'string'}
    result = inject_clean_text_patterns(field, field_info)
    assert 'normalize' not in result


@patch('ansible_base.lib.metadata.get_setting', return_value=True)
def test_inject_tier2_no_blocked_pattern_keys(mock_setting):
    field = _make_field(field_name='description')
    field_info = {'type': 'string'}
    result = inject_clean_text_patterns(field, field_info)
    blocked_keys = [k for k in result if k.startswith('blocked_pattern')]
    assert blocked_keys == []


# ---------------------------------------------------------------------------
# CleanTextMetadata
# ---------------------------------------------------------------------------


def test_clean_text_metadata_inherits_simple_metadata():
    assert issubclass(CleanTextMetadata, SimpleMetadata)


# ---------------------------------------------------------------------------
# Pattern correctness — tier 1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    'value',
    [
        'MyResource',
        'test_name',
        '_leading_underscore',
        '42numeric',
        'hello world',
        'user@example',
        'dashes-and.dots',
    ],
)
def test_tier1_pattern_accepts_valid_names(value):
    pattern = build_tier1_frontend_pattern()
    compiled = regex.compile(pattern, regex.UNICODE)
    assert compiled.match(value), f'Expected {value!r} to match tier 1 pattern'


def test_tier1_pattern_rejects_zalgo():
    pattern = build_tier1_frontend_pattern()
    compiled = regex.compile(pattern, regex.UNICODE)
    zalgo = 'test' + '̀' * 5
    assert compiled.match(zalgo) is None, 'Zalgo text should be rejected by tier 1 pattern'


def test_tier1_pattern_rejects_interleaved_zalgo():
    """Verifies the Major-2 fix: marks interleaved with base characters (not just
    consecutive runs) are now rejected too, approximating the server's
    _has_dense_combining_marks() sliding-window check."""
    pattern = build_tier1_frontend_pattern()
    compiled = regex.compile(pattern, regex.UNICODE)
    # 3 base chars + 5 combining marks (acute/grave), each mark-cluster separated by
    # exactly one base character -- passes _ZALGO_RE alone (no run of 5 consecutive
    # marks) but trips _has_dense_combining_marks() server-side (5 marks span
    # positions 1-7, diff=6 < window=8).
    interleaved_zalgo = 'a' + '́̀' + 'b' + '́̀' + 'c' + '́'
    assert compiled.match(interleaved_zalgo) is None, 'Interleaved Zalgo should be rejected by tier 1 pattern'


# ---------------------------------------------------------------------------
# Pattern correctness — tier 2
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    'value',
    [
        'Hello world',
        'This is a normal description.',
        'Line 1\nLine 2',
        '100% valid text',
        'Accented: café',
    ],
)
def test_tier2_pattern_accepts_plain_text(value):
    pattern = build_tier2_frontend_pattern()
    compiled = regex.compile(pattern, regex.IGNORECASE)
    assert compiled.match(value), f'Expected {value!r} to match tier 2 pattern'


@pytest.mark.parametrize(
    'value,reason',
    [
        ('<script>alert(1)</script>', 'HTML script tag'),
        ('<img src=x onerror=alert(1)>', 'HTML img tag'),
        ('hello\x00world', 'null byte control char'),
        ('hello\x07world', 'bell control char'),
        ('${command}', 'shell variable expansion'),
        ('$(whoami)', 'shell command substitution'),
        ('{{user.password}}', 'template expression'),
        ('{% include "x" %}', 'template tag'),
        ('javascript:alert(1)', 'javascript URI'),
        ('vbscript:run', 'vbscript URI'),
    ],
)
def test_tier2_pattern_rejects_dangerous_input(value, reason):
    pattern = build_tier2_frontend_pattern()
    compiled = regex.compile(pattern, regex.IGNORECASE)
    assert compiled.match(value) is None, f'Tier 2 should reject {reason}: {value!r}'


def test_tier2_pattern_does_not_catch_html_entity_encoded_payload():
    """Known, tracked gap (Major-3 in the AAP-85987 review): the tier-2 frontend
    pattern only matches literal, undecoded '<tag>' markup in the raw string. The
    real validate_free_text() decodes HTML entities (plus URL-encoding and NFKC)
    before parsing with a real HTML parser (nh3), so an entity-encoded payload like
    '&lt;script&gt;' IS rejected server-side but is NOT caught by this client-side
    approximation.

    This test intentionally asserts the CURRENT (accepted-by-the-pattern) behavior,
    so that a future change to build_tier2_frontend_pattern() that happens to close
    this gap changes this test too -- forcing an explicit, reviewed decision rather
    than a silent behavior change. See the docstring on build_tier2_frontend_pattern()
    for the full rationale on why this isn't fixed with a static regex.
    """
    pattern = build_tier2_frontend_pattern()
    compiled = regex.compile(pattern, regex.IGNORECASE)
    encoded_payload = '&amp;lt;script&amp;gt;alert(1)&amp;lt;/script&amp;gt;'
    assert compiled.match(encoded_payload), 'Documented gap: entity-encoded markup is not caught client-side (server-side only)'


# ---------------------------------------------------------------------------
# Integration — CleanTextMetadata through DRF's real OPTIONS pipeline
# ---------------------------------------------------------------------------


class _CleanNameDescSlugSerializer(CleanTextMixin, serializers.ModelSerializer):
    """ModelSerializer exercising the metadata/OPTIONS code path end-to-end.
    Backed by MetadataTestModel (CharField ``name``, TextField ``description``,
    SlugField ``slug``) so inject_clean_text_patterns can look up model fields
    via get_internal_type() -- the same mechanism CleanTextMixin._classify_fields
    uses server-side."""

    class Meta:
        model = MetadataTestModel
        fields = ['name', 'description', 'slug']


class _CleanTextMetadataView(generics.GenericAPIView):
    """Minimal, unregistered (no urlconf entry) view solely to drive DRF's real
    OPTIONS/metadata pipeline (SimpleMetadata.determine_metadata ->
    determine_actions -> get_serializer_info) through CleanTextMetadata, without
    touching any shared app models or views."""

    metadata_class = CleanTextMetadata
    serializer_class = _CleanNameDescSlugSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        # Never actually invoked by an OPTIONS request; only its presence is needed
        # so 'POST' appears in view.allowed_methods and determine_actions() includes it.
        return Response({})


@override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
def test_clean_text_metadata_options_response_end_to_end():
    """Jira acceptance criterion #5: at least one DAB endpoint returns `pattern` in
    its OPTIONS response for name and description fields (and omits it for
    SlugField), exercised through DRF's real OPTIONS pipeline (not mocked fields)."""

    factory = APIRequestFactory()
    request = factory.options('/')
    view = _CleanTextMetadataView.as_view()

    response = view(request)

    assert response.status_code == 200, response.data
    assert 'actions' in response.data
    post_fields = response.data['actions']['POST']

    assert 'pattern' in post_fields['name']
    assert post_fields['name']['flags'] == 'u'
    assert 'normalize' in post_fields['name']

    assert 'pattern' in post_fields['description']
    assert post_fields['description']['flags'] == 'i'

    assert 'pattern' not in post_fields['slug']


# ---------------------------------------------------------------------------
# Public API — validation_enabled
# ---------------------------------------------------------------------------


def test_validation_enabled_returns_setting_value():
    with override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True):
        assert validation_enabled() is True

    with override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=False):
        assert validation_enabled() is False


# ---------------------------------------------------------------------------
# Public API — get_tier1_pattern / get_tier2_pattern
# ---------------------------------------------------------------------------


def test_get_tier1_pattern_returns_metadata():
    result = get_tier1_pattern()
    assert 'pattern' in result
    assert result['description'] == TIER1_PATTERN_DESCRIPTION
    assert result['flags'] == 'u'
    assert result['normalize'] == 'NFC'
    assert isinstance(result['pattern'], str)


def test_get_tier2_pattern_returns_metadata():
    result = get_tier2_pattern()
    assert 'pattern' in result
    assert result['description'] == TIER2_PATTERN_DESCRIPTION
    assert result['flags'] == 'i'
    assert 'normalize' not in result
    assert isinstance(result['pattern'], str)
