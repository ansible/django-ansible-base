from unittest.mock import Mock, patch

import pytest
import regex

from ansible_base.lib.metadata import (
    CleanTextMetadata,
    _HTML_TAG_APPROX,
    _wrap_alternation,
    build_tier1_frontend_pattern,
    build_tier2_frontend_pattern,
    inject_clean_text_patterns,
)
from ansible_base.lib.serializers.mixins import CleanTextMixin
from ansible_base.lib.utils.validation import CONTROL_CHARS, _HANDLER_URI_RE, _INJECTION_RE


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
    build_tier1_frontend_pattern.cache_clear()
    assert isinstance(build_tier1_frontend_pattern(), str)


def test_tier1_pattern_starts_with_caret_lookahead():
    build_tier1_frontend_pattern.cache_clear()
    pattern = build_tier1_frontend_pattern()
    assert pattern.startswith('^(?!.*')


def test_tier1_pattern_ends_with_dollar():
    build_tier1_frontend_pattern.cache_clear()
    pattern = build_tier1_frontend_pattern()
    assert pattern.endswith('$')
    assert r'\Z' not in pattern


def test_tier1_pattern_compiles_with_regex_module():
    build_tier1_frontend_pattern.cache_clear()
    pattern = build_tier1_frontend_pattern()
    compiled = regex.compile(pattern, regex.UNICODE)
    assert compiled is not None


# ---------------------------------------------------------------------------
# build_tier2_frontend_pattern
# ---------------------------------------------------------------------------

def test_tier2_pattern_is_string():
    build_tier2_frontend_pattern.cache_clear()
    assert isinstance(build_tier2_frontend_pattern(), str)


def test_tier2_pattern_contains_deny_substrings():
    build_tier2_frontend_pattern.cache_clear()
    pattern = build_tier2_frontend_pattern()
    assert _HTML_TAG_APPROX in pattern
    assert CONTROL_CHARS in pattern
    assert _HANDLER_URI_RE.pattern in pattern
    assert _INJECTION_RE.pattern in pattern


def test_tier2_pattern_ends_with_catch_all():
    build_tier2_frontend_pattern.cache_clear()
    pattern = build_tier2_frontend_pattern()
    assert pattern.endswith(r'[\s\S]*$')


def test_tier2_pattern_compiles():
    build_tier2_frontend_pattern.cache_clear()
    pattern = build_tier2_frontend_pattern()
    compiled = regex.compile(pattern, regex.IGNORECASE)
    assert compiled is not None


# ---------------------------------------------------------------------------
# inject_clean_text_patterns — guard clauses
# ---------------------------------------------------------------------------

def _make_field(field_name='description', is_charfield=True, serializer_cls=CleanTextMixin):
    from rest_framework import serializers as drf_serializers

    field = Mock(spec=drf_serializers.CharField if is_charfield else drf_serializers.IntegerField)
    field.field_name = field_name

    serializer = Mock(spec=serializer_cls)
    serializer.name_fields = frozenset({'name', 'username', 'hostname'})
    serializer.excluded_fields = frozenset()
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
    field.parent = Mock(spec=drf_serializers.Serializer)
    field_info = {'type': 'string'}
    result = inject_clean_text_patterns(field, field_info)
    assert 'pattern' not in result


@patch('ansible_base.lib.metadata.get_setting', return_value=True)
def test_inject_returns_unmodified_for_non_charfield(mock_setting):
    field = _make_field(is_charfield=False)
    field_info = {'type': 'integer'}
    result = inject_clean_text_patterns(field, field_info)
    assert 'pattern' not in result


@patch('ansible_base.lib.metadata.get_setting', return_value=True)
def test_inject_returns_unmodified_for_excluded_field(mock_setting):
    field = _make_field(field_name='template')
    field.parent.excluded_fields = frozenset({'template'})
    field_info = {'type': 'string'}
    result = inject_clean_text_patterns(field, field_info)
    assert 'pattern' not in result


# ---------------------------------------------------------------------------
# inject_clean_text_patterns — tier 1
# ---------------------------------------------------------------------------

@patch('ansible_base.lib.metadata.get_setting', return_value=True)
def test_inject_tier1_keys(mock_setting):
    build_tier1_frontend_pattern.cache_clear()
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
# inject_clean_text_patterns — tier 2
# ---------------------------------------------------------------------------

@patch('ansible_base.lib.metadata.get_setting', return_value=True)
def test_inject_tier2_keys(mock_setting):
    build_tier2_frontend_pattern.cache_clear()
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

@pytest.mark.parametrize('value', [
    'MyResource',
    'test_name',
    '_leading_underscore',
    '42numeric',
    'hello world',
    'user@example',
    'dashes-and.dots',
])
def test_tier1_pattern_accepts_valid_names(value):
    build_tier1_frontend_pattern.cache_clear()
    pattern = build_tier1_frontend_pattern()
    compiled = regex.compile(pattern, regex.UNICODE)
    assert compiled.match(value), f'Expected {value!r} to match tier 1 pattern'


def test_tier1_pattern_rejects_zalgo():
    build_tier1_frontend_pattern.cache_clear()
    pattern = build_tier1_frontend_pattern()
    compiled = regex.compile(pattern, regex.UNICODE)
    zalgo = 'test' + '̀' * 5
    assert compiled.match(zalgo) is None, 'Zalgo text should be rejected by tier 1 pattern'


# ---------------------------------------------------------------------------
# Pattern correctness — tier 2
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('value', [
    'Hello world',
    'This is a normal description.',
    'Line 1\nLine 2',
    '100% valid text',
    'Accented: café',
])
def test_tier2_pattern_accepts_plain_text(value):
    build_tier2_frontend_pattern.cache_clear()
    pattern = build_tier2_frontend_pattern()
    compiled = regex.compile(pattern, regex.IGNORECASE)
    assert compiled.match(value), f'Expected {value!r} to match tier 2 pattern'


@pytest.mark.parametrize('value,reason', [
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
])
def test_tier2_pattern_rejects_dangerous_input(value, reason):
    build_tier2_frontend_pattern.cache_clear()
    pattern = build_tier2_frontend_pattern()
    compiled = regex.compile(pattern, regex.IGNORECASE)
    assert compiled.match(value) is None, f'Tier 2 should reject {reason}: {value!r}'
