import logging
from unittest import mock

import pytest
from django.test import RequestFactory, override_settings
from rest_framework import serializers

from ansible_base.lib.serializers.mixins import CleanTextMixin
from test_app.models import City, Organization, User


@pytest.fixture
def enable_validation(settings):
    settings.ENHANCED_INPUT_VALIDATION_ENABLED = True


class OrgSerializer(CleanTextMixin, serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ['name', 'description', 'extra_field']


class OrgSerializerWithExclusions(CleanTextMixin, serializers.ModelSerializer):
    excluded_fields = frozenset({'description'})

    class Meta:
        model = Organization
        fields = ['name', 'description', 'extra_field']


class CitySerializer(CleanTextMixin, serializers.ModelSerializer):
    class Meta:
        model = City
        fields = ['name', 'country', 'population', 'extra_data']


class CitySerializerWithExcludedJsonField(CleanTextMixin, serializers.ModelSerializer):
    excluded_fields = frozenset({'extra_data'})

    class Meta:
        model = City
        fields = ['name', 'country', 'population', 'extra_data']


class CitySerializerWithExcludedJsonKeys(CleanTextMixin, serializers.ModelSerializer):
    excluded_json_keys = {'extra_data': frozenset({'template_content', 'ssh_key_data'})}

    class Meta:
        model = City
        fields = ['name', 'country', 'population', 'extra_data']


@pytest.mark.usefixtures('enable_validation')
class TestCleanTextMixinTier1:
    """Tier 1: strict allowlist for name fields."""

    @pytest.mark.django_db
    def test_valid_name_accepted(self):
        data = {'name': 'My Org', 'description': 'A test org'}
        serializer = OrgSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        'name',
        [
            'simple',
            'With Spaces',
            'under_score',
            'dot.name',
            'user@org',
            'hyphen-name',
        ],
        ids=['simple', 'spaces', 'underscore', 'dot', 'at-sign', 'hyphen'],
    )
    def test_allowed_characters_in_name(self, name):
        data = {'name': name}
        serializer = OrgSerializer(data=data)
        serializer.is_valid()
        assert 'name' not in serializer.errors

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        'name',
        [
            '<script>alert(1)</script>',
            'name\x00null',
            'semi;colon',
            'back`tick',
        ],
        ids=['html-tag', 'null-byte', 'semicolon', 'backtick'],
    )
    def test_disallowed_characters_in_name(self, name):
        data = {'name': name, 'description': 'valid'}
        serializer = OrgSerializer(data=data)
        assert not serializer.is_valid()
        assert 'name' in serializer.errors


@pytest.mark.usefixtures('enable_validation')
class TestCleanTextMixinTier2:
    """Tier 2: dangerous pattern blocklist for non-name text fields."""

    @pytest.mark.django_db
    def test_clean_description_accepted(self):
        data = {'name': 'Org', 'description': 'A perfectly fine description.'}
        serializer = OrgSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        'bad_value',
        [
            '<script>alert("xss")</script>',
            '<iframe src="evil.com">',
            '<object data="bad">',
            'javascript:alert(1)',
            'vbscript:run',
            'data:text/html,<h1>hi</h1>',
            '$(rm -rf /)',
            '${USER}',
            'text\x00with\x01control\x02chars',
        ],
        ids=[
            'script-tag',
            'iframe-tag',
            'object-tag',
            'javascript-uri',
            'vbscript-uri',
            'data-uri',
            'shell-subst-paren',
            'shell-subst-brace',
            'control-chars',
        ],
    )
    def test_dangerous_pattern_rejected_in_description(self, bad_value):
        data = {'name': 'Org', 'description': bad_value}
        serializer = OrgSerializer(data=data)
        assert not serializer.is_valid()
        assert 'description' in serializer.errors

    @pytest.mark.django_db
    def test_dangerous_pattern_rejected_in_extra_field(self):
        data = {'name': 'Org', 'extra_field': '<script>bad</script>'}
        serializer = OrgSerializer(data=data)
        assert not serializer.is_valid()
        assert 'extra_field' in serializer.errors

    @pytest.mark.django_db
    def test_all_html_tags_rejected(self):
        data = {'name': 'Org', 'description': 'Use <b>bold</b> and <em>emphasis</em>'}
        serializer = OrgSerializer(data=data)
        assert not serializer.is_valid()
        assert 'description' in serializer.errors


@pytest.mark.usefixtures('enable_validation')
class TestCleanTextMixinGrandfathering:
    """Existing values on update are grandfathered (skipped)."""

    @pytest.mark.django_db
    def test_unchanged_dangerous_value_accepted_on_update(self):
        org = Organization.objects.create(name='Org', description='$(dangerous)')
        data = {'name': 'Org', 'description': '$(dangerous)'}
        serializer = OrgSerializer(org, data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    def test_changed_value_still_validated_on_update(self):
        org = Organization.objects.create(name='Org', description='safe')
        data = {'name': 'Org', 'description': '<script>evil</script>'}
        serializer = OrgSerializer(org, data=data)
        assert not serializer.is_valid()
        assert 'description' in serializer.errors

    @pytest.mark.django_db
    def test_unchanged_name_accepted_on_update(self):
        org = Organization.objects.create(name='Org;bad')
        data = {'name': 'Org;bad'}
        serializer = OrgSerializer(org, data=data)
        serializer.is_valid()
        assert 'name' not in serializer.errors


@pytest.mark.usefixtures('enable_validation')
class TestCleanTextMixinExcludedFields:
    """Fields listed in excluded_fields are skipped entirely."""

    @pytest.mark.django_db
    def test_excluded_field_allows_dangerous_content(self):
        data = {'name': 'Org', 'description': '<script>alert(1)</script>'}
        serializer = OrgSerializerWithExclusions(data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    def test_non_excluded_field_still_validated(self):
        data = {'name': 'Org', 'extra_field': '<script>alert(1)</script>'}
        serializer = OrgSerializerWithExclusions(data=data)
        assert not serializer.is_valid()
        assert 'extra_field' in serializer.errors


@pytest.mark.usefixtures('enable_validation')
class TestCleanTextMixinEdgeCases:
    """Edge cases: non-string values, missing fields, partial updates."""

    @pytest.mark.django_db
    def test_empty_string_passes_validation(self):
        """An empty string is a valid value for a text field."""
        data = {'name': 'Org', 'description': ''}
        serializer = OrgSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    def test_partial_update_only_validates_submitted_fields(self):
        org = Organization.objects.create(name='Org', description='$(dangerous)')
        data = {'extra_field': 'safe value'}
        serializer = OrgSerializer(org, data=data, partial=True)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    def test_multiple_errors_reported_together(self):
        data = {
            'name': '<script>bad</script>',
            'description': '$(evil)',
            'extra_field': '${PWD}',
        }
        serializer = OrgSerializer(data=data)
        assert not serializer.is_valid()
        assert 'name' in serializer.errors
        assert 'description' in serializer.errors
        assert 'extra_field' in serializer.errors


@pytest.mark.usefixtures('enable_validation')
class TestCleanTextMixinJSONFieldCreate:
    """JSONField validation: string values in dicts are validated on create."""

    @pytest.mark.django_db
    def test_clean_json_dict_accepted(self):
        data = {'name': 'TestCity', 'extra_data': {'host': 'example.com', 'port': 443}}
        serializer = CitySerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    def test_dangerous_string_in_json_dict_rejected(self):
        data = {'name': 'TestCity', 'extra_data': {'host': '<script>alert(1)</script>'}}
        serializer = CitySerializer(data=data)
        assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors
        assert 'host' in serializer.errors['extra_data']

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        'bad_value',
        [
            '<script>alert("xss")</script>',
            '$(rm -rf /)',
            '${USER}',
            'javascript:alert(1)',
            '{{config.secret}}',
        ],
        ids=['script-tag', 'shell-subst-paren', 'shell-subst-brace', 'javascript-uri', 'template-injection'],
    )
    def test_various_dangerous_patterns_in_json_rejected(self, bad_value):
        data = {'name': 'TestCity', 'extra_data': {'username': bad_value}}
        serializer = CitySerializer(data=data)
        assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors
        assert 'username' in serializer.errors['extra_data']

    @pytest.mark.django_db
    def test_multiple_bad_keys_reported_together(self):
        data = {
            'name': 'TestCity',
            'extra_data': {
                'host': '<script>bad</script>',
                'callback_url': 'javascript:evil()',
            },
        }
        serializer = CitySerializer(data=data)
        assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors
        assert 'host' in serializer.errors['extra_data']
        assert 'callback_url' in serializer.errors['extra_data']

    @pytest.mark.django_db
    def test_non_string_values_skipped(self):
        """Non-string sub-values (int, bool, None, list) are not validated."""
        data = {
            'name': 'TestCity',
            'extra_data': {
                'port': 8080,
                'enabled': True,
                'tags': ['web', 'prod'],
                'metadata': None,
            },
        }
        serializer = CitySerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    def test_empty_dict_accepted(self):
        data = {'name': 'TestCity', 'extra_data': {}}
        serializer = CitySerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    def test_null_json_field_accepted(self):
        data = {'name': 'TestCity', 'extra_data': None}
        serializer = CitySerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    def test_bare_string_json_field_rejected(self):
        """A bare string as the entire JSONField value is validated."""
        data = {'name': 'TestCity', 'extra_data': '<script>alert(1)</script>'}
        serializer = CitySerializer(data=data)
        assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors
        assert isinstance(
            serializer.errors['extra_data'], list
        ), f"Expected flat error list, got {type(serializer.errors['extra_data'])}: {serializer.errors['extra_data']}"

    @pytest.mark.django_db
    def test_bare_safe_string_json_field_accepted(self):
        """A bare string without dangerous patterns passes validation."""
        data = {'name': 'TestCity', 'extra_data': 'just a plain string'}
        serializer = CitySerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    def test_bare_string_json_field_grandfathered_on_update(self):
        """A bare-string JSONField value is grandfathered if unchanged on update."""
        city = City.objects.create(name='OldCity', extra_data='$(dangerous)')
        data = {'name': 'OldCity', 'extra_data': '$(dangerous)'}
        serializer = CitySerializer(city, data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    def test_bare_string_json_field_validated_when_changed_on_update(self):
        """A changed bare-string JSONField value is validated on update."""
        city = City.objects.create(name='OldCity', extra_data='safe value')
        data = {'name': 'OldCity', 'extra_data': '<script>evil</script>'}
        serializer = CitySerializer(city, data=data)
        assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors


@pytest.mark.usefixtures('enable_validation')
class TestCleanTextMixinJSONFieldUpdate:
    """JSONField validation: sub-key grandfathering on update."""

    @pytest.mark.django_db
    def test_unchanged_dangerous_subkey_accepted_on_update(self):
        """Grandfathering: unchanged sub-keys are skipped even if they contain dangerous content."""
        city = City.objects.create(name='OldCity', extra_data={'host': '$(dangerous)'})
        data = {'name': 'OldCity', 'extra_data': {'host': '$(dangerous)'}}
        serializer = CitySerializer(city, data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    def test_changed_subkey_validated_on_update(self):
        """Changed sub-keys are validated on update."""
        city = City.objects.create(name='OldCity', extra_data={'host': 'safe.example.com'})
        data = {'name': 'OldCity', 'extra_data': {'host': '<script>evil</script>'}}
        serializer = CitySerializer(city, data=data)
        assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors
        assert 'host' in serializer.errors['extra_data']

    @pytest.mark.django_db
    def test_new_subkey_validated_on_update(self):
        """New sub-keys (not present in stored value) are validated on update."""
        city = City.objects.create(name='OldCity', extra_data={'host': 'safe.example.com'})
        data = {'name': 'OldCity', 'extra_data': {'host': 'safe.example.com', 'callback': '$(evil)'}}
        serializer = CitySerializer(city, data=data)
        assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors
        assert 'callback' in serializer.errors['extra_data']

    @pytest.mark.django_db
    def test_mixed_changed_and_unchanged_subkeys(self):
        """Only changed sub-keys produce errors; unchanged ones are grandfathered."""
        city = City.objects.create(name='OldCity', extra_data={'host': '$(old_dangerous)', 'port': '8080'})
        data = {'name': 'OldCity', 'extra_data': {'host': '$(old_dangerous)', 'port': '<script>new</script>'}}
        serializer = CitySerializer(city, data=data)
        assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors
        assert 'host' not in serializer.errors['extra_data']
        assert 'port' in serializer.errors['extra_data']

    @pytest.mark.django_db
    def test_partial_update_skips_absent_json_field(self):
        """Partial update without the JSONField does not trigger validation."""
        city = City.objects.create(name='OldCity', extra_data={'host': '$(dangerous)'})
        data = {'name': 'NewCity'}
        serializer = CitySerializer(city, data=data, partial=True)
        assert serializer.is_valid(), serializer.errors


@pytest.mark.usefixtures('enable_validation')
class TestCleanTextMixinJSONFieldExcluded:
    """JSONField exclusion mechanisms."""

    @pytest.mark.django_db
    def test_excluded_json_field_allows_dangerous_content(self):
        """Entire JSONField listed in excluded_fields skips validation."""
        data = {'name': 'TestCity', 'extra_data': {'host': '<script>alert(1)</script>'}}
        serializer = CitySerializerWithExcludedJsonField(data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    def test_excluded_json_keys_allows_specific_subkeys(self):
        """Sub-keys listed in excluded_json_keys are skipped."""
        data = {
            'name': 'TestCity',
            'extra_data': {
                'template_content': '{{dangerous.template}}',
                'ssh_key_data': '-----BEGIN RSA PRIVATE KEY-----\n$(not-shell)',
            },
        }
        serializer = CitySerializerWithExcludedJsonKeys(data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    def test_non_excluded_json_keys_still_validated(self):
        """Sub-keys NOT in excluded_json_keys are still validated."""
        data = {
            'name': 'TestCity',
            'extra_data': {
                'template_content': '{{safe.because.excluded}}',
                'host': '<script>not excluded</script>',
            },
        }
        serializer = CitySerializerWithExcludedJsonKeys(data=data)
        assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors
        assert 'host' in serializer.errors['extra_data']
        assert 'template_content' not in serializer.errors['extra_data']


@pytest.mark.usefixtures('enable_validation')
class TestCleanTextMixinJSONFieldListOfDicts:
    """JSONField validation: list-of-dicts traversal."""

    @pytest.mark.django_db
    def test_clean_list_of_dicts_accepted(self):
        data = {
            'name': 'TestCity',
            'extra_data': [
                {'url': 'https://example.com', 'label': 'Homepage'},
                {'url': 'https://docs.example.com', 'label': 'Docs'},
            ],
        }
        serializer = CitySerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    def test_dangerous_value_in_list_of_dicts_rejected(self):
        data = {
            'name': 'TestCity',
            'extra_data': [
                {'url': 'https://safe.com', 'label': 'OK'},
                {'url': 'javascript:alert(1)', 'label': 'Bad'},
            ],
        }
        serializer = CitySerializer(data=data)
        assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors
        assert '[1].url' in serializer.errors['extra_data']

    @pytest.mark.django_db
    def test_list_of_dicts_grandfathering_on_update(self):
        """Unchanged values in a list-of-dicts are grandfathered regardless of position."""
        stored = [{'url': '$(dangerous)', 'label': 'Legacy'}]
        city = City.objects.create(name='OldCity', extra_data=stored)
        data = {'name': 'OldCity', 'extra_data': [{'url': '$(dangerous)', 'label': 'Legacy'}]}
        serializer = CitySerializer(city, data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    def test_list_of_dicts_reorder_validates_moved_items(self):
        """Reordering items counts as a change — dangerous values at new positions are validated."""
        stored = [
            {'url': '$(first)', 'label': 'A'},
            {'url': 'https://safe.com', 'label': 'B'},
        ]
        city = City.objects.create(name='OldCity', extra_data=stored)
        data = {
            'name': 'OldCity',
            'extra_data': [
                {'url': 'https://safe.com', 'label': 'B'},
                {'url': '$(first)', 'label': 'A'},
            ],
        }
        serializer = CitySerializer(city, data=data)
        assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors
        assert '[1].url' in serializer.errors['extra_data']

    @pytest.mark.django_db
    def test_list_of_dicts_unchanged_position_grandfathered(self):
        """Items at the same position with unchanged values are grandfathered."""
        stored = [
            {'url': '$(dangerous)', 'label': 'Legacy'},
            {'url': 'https://safe.com', 'label': 'OK'},
        ]
        city = City.objects.create(name='OldCity', extra_data=stored)
        data = {
            'name': 'OldCity',
            'extra_data': [
                {'url': '$(dangerous)', 'label': 'Legacy'},
                {'url': 'https://safe.com', 'label': 'OK'},
            ],
        }
        serializer = CitySerializer(city, data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    def test_list_of_dicts_duplicating_dangerous_value_rejected(self):
        """Duplicating a grandfathered dangerous value into a new entry is rejected."""
        stored = [{'url': '$(dangerous)', 'label': 'Legacy'}]
        city = City.objects.create(name='OldCity', extra_data=stored)
        data = {
            'name': 'OldCity',
            'extra_data': [
                {'url': '$(dangerous)', 'label': 'Legacy'},
                {'url': '$(dangerous)', 'label': 'Copy'},
            ],
        }
        serializer = CitySerializer(city, data=data)
        assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors
        assert '[1].url' in serializer.errors['extra_data']

    @pytest.mark.django_db
    def test_list_of_dicts_changed_item_validated(self):
        """Changed items in a list-of-dicts are validated."""
        stored = [{'url': 'https://safe.com', 'label': 'OK'}]
        city = City.objects.create(name='OldCity', extra_data=stored)
        data = {'name': 'OldCity', 'extra_data': [{'url': '<script>evil</script>', 'label': 'OK'}]}
        serializer = CitySerializer(city, data=data)
        assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors
        assert '[0].url' in serializer.errors['extra_data']

    @pytest.mark.django_db
    def test_non_string_non_container_items_in_list_accepted(self):
        """Non-string, non-container items (int, bool) in a list pass validation."""
        data = {'name': 'TestCity', 'extra_data': [42, True]}
        serializer = CitySerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    def test_excluded_json_keys_applies_to_list_of_dicts(self):
        """excluded_json_keys also applies when traversing list-of-dicts."""
        data = {
            'name': 'TestCity',
            'extra_data': [
                {'template_content': '{{dangerous}}', 'host': '<script>bad</script>'},
            ],
        }
        serializer = CitySerializerWithExcludedJsonKeys(data=data)
        assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors
        assert '[0].host' in serializer.errors['extra_data']
        assert '[0].template_content' not in serializer.errors['extra_data']


@pytest.mark.usefixtures('enable_validation')
class TestCleanTextMixinJSONRecursive:
    """JSONField validation: recursive traversal into nested structures."""

    @pytest.mark.django_db
    def test_nested_dict_dangerous_value_rejected(self):
        data = {'name': 'TestCity', 'extra_data': {'config': {'inner': '<script>bad</script>'}}}
        serializer = CitySerializer(data=data)
        assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors
        assert 'config.inner' in serializer.errors['extra_data']

    @pytest.mark.django_db
    def test_nested_dict_safe_value_accepted(self):
        data = {'name': 'TestCity', 'extra_data': {'config': {'inner': 'safe text'}}}
        serializer = CitySerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    def test_deeply_nested_value_rejected(self):
        data = {'name': 'TestCity', 'extra_data': {'a': {'b': {'c': '<script>deep</script>'}}}}
        serializer = CitySerializer(data=data)
        assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors
        assert 'a.b.c' in serializer.errors['extra_data']

    @pytest.mark.django_db
    def test_nested_list_in_dict_rejected(self):
        data = {'name': 'TestCity', 'extra_data': {'items': [{'host': '<script>x</script>'}]}}
        serializer = CitySerializer(data=data)
        assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors
        assert 'items[0].host' in serializer.errors['extra_data']

    @pytest.mark.django_db
    def test_bare_strings_in_list_validated(self):
        data = {'name': 'TestCity', 'extra_data': ['<script>bad</script>', 'safe text']}
        serializer = CitySerializer(data=data)
        assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors
        assert '[0]' in serializer.errors['extra_data']
        assert '[1]' not in serializer.errors['extra_data']

    @pytest.mark.django_db
    def test_nested_list_of_lists_rejected(self):
        data = {'name': 'TestCity', 'extra_data': [['<script>bad</script>']]}
        serializer = CitySerializer(data=data)
        assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors
        assert '[0][0]' in serializer.errors['extra_data']

    @pytest.mark.django_db
    def test_max_json_depth_rejects_input(self, caplog):
        """Input beyond _MAX_JSON_DEPTH (10) is rejected (fail closed) and a warning is logged."""
        nested = '<script>deep</script>'
        for _ in range(11):
            nested = {'k': nested}
        data = {'name': 'TestCity', 'extra_data': nested}
        serializer = CitySerializer(data=data)
        with caplog.at_level(logging.WARNING, logger='ansible_base.lib.serializers.mixins'):
            assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors
        assert any('depth limit' in r.message for r in caplog.records)

    @pytest.mark.django_db
    def test_value_at_max_json_depth_is_validated(self):
        """Dangerous value at exactly depth 10 is still caught."""
        nested = '<script>deep</script>'
        for _ in range(10):
            nested = {'k': nested}
        data = {'name': 'TestCity', 'extra_data': nested}
        serializer = CitySerializer(data=data)
        assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors


@pytest.mark.usefixtures('enable_validation')
class TestCleanTextMixinJSONRecursiveGrandfathering:
    """JSONField validation: grandfathering works at every nesting level."""

    @pytest.mark.django_db
    def test_unchanged_nested_dict_grandfathered(self):
        stored = {'config': {'inner': '$(old_dangerous)'}}
        city = City.objects.create(name='OldCity', extra_data=stored)
        data = {'name': 'OldCity', 'extra_data': {'config': {'inner': '$(old_dangerous)'}}}
        serializer = CitySerializer(city, data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    def test_changed_nested_value_validated(self):
        stored = {'config': {'inner': 'was_safe'}}
        city = City.objects.create(name='OldCity', extra_data=stored)
        data = {'name': 'OldCity', 'extra_data': {'config': {'inner': '<script>new</script>'}}}
        serializer = CitySerializer(city, data=data)
        assert not serializer.is_valid()
        assert 'config.inner' in serializer.errors['extra_data']

    @pytest.mark.django_db
    def test_mixed_changed_unchanged_nested(self):
        stored = {'config': {'kept': '$(old)', 'changed': 'was_safe'}}
        city = City.objects.create(name='OldCity', extra_data=stored)
        data = {'name': 'OldCity', 'extra_data': {'config': {'kept': '$(old)', 'changed': '<script>new</script>'}}}
        serializer = CitySerializer(city, data=data)
        assert not serializer.is_valid()
        assert 'config.kept' not in serializer.errors['extra_data']
        assert 'config.changed' in serializer.errors['extra_data']

    @pytest.mark.django_db
    def test_unchanged_nested_list_item_grandfathered(self):
        stored = {'items': [{'host': '$(old)'}]}
        city = City.objects.create(name='OldCity', extra_data=stored)
        data = {'name': 'OldCity', 'extra_data': {'items': [{'host': '$(old)'}]}}
        serializer = CitySerializer(city, data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    def test_deeply_nested_grandfathering(self):
        stored = {'a': {'b': {'c': '$(deep_old)'}}}
        city = City.objects.create(name='OldCity', extra_data=stored)
        data = {'name': 'OldCity', 'extra_data': {'a': {'b': {'c': '$(deep_old)'}}}}
        serializer = CitySerializer(city, data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    def test_new_nested_key_validated_on_update(self):
        stored = {'config': {}}
        city = City.objects.create(name='OldCity', extra_data=stored)
        data = {'name': 'OldCity', 'extra_data': {'config': {'new_key': '<script>bad</script>'}}}
        serializer = CitySerializer(city, data=data)
        assert not serializer.is_valid()
        assert 'config.new_key' in serializer.errors['extra_data']

    @pytest.mark.django_db
    def test_bare_string_in_list_grandfathered(self):
        stored = ['$(old_value)']
        city = City.objects.create(name='OldCity', extra_data=stored)
        data = {'name': 'OldCity', 'extra_data': ['$(old_value)']}
        serializer = CitySerializer(city, data=data)
        assert serializer.is_valid(), serializer.errors


MIXIN_LOGGER = 'ansible_base.lib.serializers.mixins'


def _make_request(user, remote_addr='10.0.0.1'):
    request = RequestFactory().post('/api/v1/organizations/')
    request.user = user
    request.META['REMOTE_ADDR'] = remote_addr
    return request


class TestCleanTextMixinAuditLogging:
    """Validation failures emit audit log entries with the required fields."""

    @pytest.mark.django_db
    def test_no_log_for_valid_input(self, caplog):
        user = User.objects.create(username='gooduser')
        data = {'name': 'Safe Org', 'description': 'Perfectly fine text'}
        ctx = {'request': _make_request(user)}
        with caplog.at_level(logging.WARNING, logger=MIXIN_LOGGER):
            serializer = OrgSerializer(data=data, context=ctx)
            serializer.is_valid()
        assert not [r for r in caplog.records if r.name == MIXIN_LOGGER]

    @pytest.mark.django_db
    def test_log_on_name_rejection(self, caplog):
        user = User.objects.create(username='testadmin')
        payload = '<script>alert(1)</script>'
        data = {'name': payload, 'description': 'ok'}
        ctx = {'request': _make_request(user, remote_addr='192.168.1.42')}
        with caplog.at_level(logging.WARNING, logger=MIXIN_LOGGER):
            serializer = OrgSerializer(data=data, context=ctx)
            serializer.is_valid()
        records = [r for r in caplog.records if r.name == MIXIN_LOGGER]
        assert len(records) == 1
        msg = records[0].message
        assert "'name'" in msg
        assert 'test_app.Organization' in msg
        assert 'for user testadmin' in msg
        assert 'ip 192.168.1.42' in msg
        assert 'valid name' in msg
        assert payload not in msg

    @pytest.mark.django_db
    def test_log_on_free_text_rejection(self, caplog):
        user = User.objects.create(username='alice')
        payload = '$(rm -rf /)'
        data = {'name': 'Org', 'description': payload}
        ctx = {'request': _make_request(user)}
        with caplog.at_level(logging.WARNING, logger=MIXIN_LOGGER):
            serializer = OrgSerializer(data=data, context=ctx)
            serializer.is_valid()
        records = [r for r in caplog.records if r.name == MIXIN_LOGGER]
        assert len(records) == 1
        msg = records[0].message
        assert "'description'" in msg
        assert 'test_app.Organization' in msg
        assert "can't include" in msg
        assert payload not in msg

    @pytest.mark.django_db
    def test_raw_payload_not_in_log(self, caplog):
        """The raw malicious input must never appear in the log message."""
        user = User.objects.create(username='attacker')
        xss = '<script>document.cookie</script>'
        data = {'name': xss, 'description': xss}
        ctx = {'request': _make_request(user)}
        with caplog.at_level(logging.WARNING, logger=MIXIN_LOGGER):
            serializer = OrgSerializer(data=data, context=ctx)
            serializer.is_valid()
        for record in caplog.records:
            if record.name == MIXIN_LOGGER:
                assert xss not in record.message

    @pytest.mark.django_db
    def test_multiple_rejections_produce_multiple_logs(self, caplog):
        user = User.objects.create(username='multi')
        data = {'name': '<bad>', 'description': '$(evil)', 'extra_field': '${PWD}'}
        ctx = {'request': _make_request(user)}
        with caplog.at_level(logging.WARNING, logger=MIXIN_LOGGER):
            serializer = OrgSerializer(data=data, context=ctx)
            serializer.is_valid()
        records = [r for r in caplog.records if r.name == MIXIN_LOGGER]
        logged_msgs = [r.message for r in records]
        assert any("'name'" in m for m in logged_msgs)
        assert any("'description'" in m for m in logged_msgs)
        assert any("'extra_field'" in m for m in logged_msgs)

    @pytest.mark.django_db
    def test_no_log_for_grandfathered_values(self, caplog):
        user = User.objects.create(username='updater')
        org = Organization.objects.create(name='Org', description='$(old_dangerous)')
        data = {'name': 'Org', 'description': '$(old_dangerous)'}
        ctx = {'request': _make_request(user)}
        with caplog.at_level(logging.WARNING, logger=MIXIN_LOGGER):
            serializer = OrgSerializer(org, data=data, context=ctx)
            serializer.is_valid()
        assert not [r for r in caplog.records if r.name == MIXIN_LOGGER]

    @pytest.mark.django_db
    def test_ip_from_x_forwarded_for(self, caplog):
        user = User.objects.create(username='proxied')
        request = _make_request(user)
        request.META['HTTP_X_FORWARDED_FOR'] = '203.0.113.50, 10.0.0.1'
        data = {'name': 'Org', 'description': '<script>x</script>'}
        with caplog.at_level(logging.WARNING, logger=MIXIN_LOGGER):
            serializer = OrgSerializer(data=data, context={'request': request})
            serializer.is_valid()
        records = [r for r in caplog.records if r.name == MIXIN_LOGGER]
        assert len(records) == 1
        assert 'ip 203.0.113.50' in records[0].message

    @pytest.mark.django_db
    def test_xff_newline_stripped_from_log(self, caplog):
        """Control characters in X-Forwarded-For must not split log lines."""
        user = User.objects.create(username='xfftest')
        request = _make_request(user)
        request.META['HTTP_X_FORWARDED_FOR'] = '10.0.0.1\nWARNING Fake audit entry'
        data = {'name': 'Org', 'description': '<script>x</script>'}
        with caplog.at_level(logging.WARNING, logger=MIXIN_LOGGER):
            serializer = OrgSerializer(data=data, context={'request': request})
            serializer.is_valid()
        records = [r for r in caplog.records if r.name == MIXIN_LOGGER]
        assert len(records) == 1
        assert '\n' not in records[0].message

    @pytest.mark.django_db
    def test_log_without_request_context(self, caplog):
        """Logging still works when no request context is available."""
        data = {'name': 'Org', 'description': '<script>x</script>'}
        with caplog.at_level(logging.WARNING, logger=MIXIN_LOGGER):
            serializer = OrgSerializer(data=data)
            serializer.is_valid()
        records = [r for r in caplog.records if r.name == MIXIN_LOGGER]
        assert len(records) == 1
        msg = records[0].message
        assert 'Validation rejected' in msg
        assert 'for user' not in msg
        assert '(ip' not in msg

    @pytest.mark.django_db
    def test_json_field_rejection_logged(self, caplog):
        user = User.objects.create(username='jsontester')
        data = {'name': 'TestCity', 'extra_data': {'host': '<script>bad</script>'}}
        ctx = {'request': _make_request(user)}
        with caplog.at_level(logging.WARNING, logger=MIXIN_LOGGER):
            serializer = CitySerializer(data=data, context=ctx)
            serializer.is_valid()
        records = [r for r in caplog.records if r.name == MIXIN_LOGGER]
        assert len(records) == 1
        msg = records[0].message
        assert 'test_app.City' in msg
        assert "'extra_data.host'" in msg
        assert 'for user jsontester' in msg
        assert '<script>bad</script>' not in msg

    @pytest.mark.django_db
    def test_json_list_of_dicts_rejection_logged(self, caplog):
        user = User.objects.create(username='listtester')
        data = {
            'name': 'TestCity',
            'extra_data': [
                {'url': 'https://safe.com'},
                {'url': 'javascript:alert(1)'},
            ],
        }
        ctx = {'request': _make_request(user)}
        with caplog.at_level(logging.WARNING, logger=MIXIN_LOGGER):
            serializer = CitySerializer(data=data, context=ctx)
            serializer.is_valid()
        records = [r for r in caplog.records if r.name == MIXIN_LOGGER]
        assert len(records) == 1
        assert "'extra_data.[1].url'" in records[0].message

    @pytest.mark.django_db
    def test_json_key_newline_stripped_from_log(self, caplog):
        """Control characters in JSON keys must not split log lines."""
        user = User.objects.create(username='keytester')
        data = {'name': 'TestCity', 'extra_data': {'host\nWARNING Fake entry': '<script>x</script>'}}
        ctx = {'request': _make_request(user)}
        with caplog.at_level(logging.WARNING, logger=MIXIN_LOGGER):
            serializer = CitySerializer(data=data, context=ctx)
            serializer.is_valid()
        records = [r for r in caplog.records if r.name == MIXIN_LOGGER]
        assert len(records) == 1
        assert '\n' not in records[0].message


class TestCleanTextMixinToggle:
    """ENHANCED_INPUT_VALIDATION_ENABLED controls whether errors are raised."""

    @pytest.mark.django_db
    @override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=False)
    def test_toggle_off_allows_invalid_name(self):
        data = {'name': '<script>alert(1)</script>', 'description': 'safe'}
        serializer = OrgSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    @override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=False)
    def test_toggle_off_allows_invalid_text(self):
        data = {'name': 'ValidOrg', 'description': '<script>alert(1)</script>'}
        serializer = OrgSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.django_db
    @override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
    def test_toggle_on_rejects_invalid_name(self):
        data = {'name': '<script>alert(1)</script>', 'description': 'safe'}
        serializer = OrgSerializer(data=data)
        assert not serializer.is_valid()
        assert 'name' in serializer.errors

    @pytest.mark.django_db
    @override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
    def test_toggle_on_rejects_invalid_text(self):
        data = {'name': 'ValidOrg', 'description': '<script>alert(1)</script>'}
        serializer = OrgSerializer(data=data)
        assert not serializer.is_valid()
        assert 'description' in serializer.errors

    @pytest.mark.django_db
    @override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=False)
    def test_toggle_off_still_logs(self, caplog):
        user = User.objects.create(username='toggletester')
        data = {'name': '<script>alert(1)</script>', 'description': 'safe'}
        ctx = {'request': _make_request(user)}
        with caplog.at_level(logging.WARNING, logger=MIXIN_LOGGER):
            serializer = OrgSerializer(data=data, context=ctx)
            assert serializer.is_valid(), serializer.errors
        records = [r for r in caplog.records if r.name == MIXIN_LOGGER]
        assert len(records) >= 1
        assert 'name' in records[0].message


class TestCleanTextMixinUnexpectedErrors:
    """Unexpected exceptions in validators are caught and handled gracefully."""

    @pytest.mark.django_db
    @override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
    @mock.patch('ansible_base.lib.serializers.mixins.validate_free_text', side_effect=RuntimeError('nh3 crash'))
    def test_unexpected_error_in_text_field_returns_generic_error(self, _mock, caplog):
        data = {'name': 'Org', 'description': 'normal text'}
        with caplog.at_level(logging.ERROR, logger=MIXIN_LOGGER):
            serializer = OrgSerializer(data=data)
            assert not serializer.is_valid()
        assert 'description' in serializer.errors
        assert 'Validation could not be completed' in str(serializer.errors['description'])
        assert any('Unexpected error validating field' in r.message for r in caplog.records)

    @pytest.mark.django_db
    @override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=False)
    @mock.patch('ansible_base.lib.serializers.mixins.validate_free_text', side_effect=RuntimeError('nh3 crash'))
    def test_unexpected_error_in_text_field_logged_but_passes_when_off(self, _mock, caplog):
        data = {'name': 'Org', 'description': 'normal text'}
        with caplog.at_level(logging.ERROR, logger=MIXIN_LOGGER):
            serializer = OrgSerializer(data=data)
            assert serializer.is_valid(), serializer.errors
        assert any('Unexpected error validating field' in r.message for r in caplog.records)

    @pytest.mark.django_db
    @override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
    @mock.patch('ansible_base.lib.serializers.mixins.validate_resource_name', side_effect=RuntimeError('regex crash'))
    def test_unexpected_error_in_name_field_returns_generic_error(self, _mock, caplog):
        data = {'name': 'Org', 'description': 'safe'}
        with caplog.at_level(logging.ERROR, logger=MIXIN_LOGGER):
            serializer = OrgSerializer(data=data)
            assert not serializer.is_valid()
        assert 'name' in serializer.errors
        assert 'Validation could not be completed' in str(serializer.errors['name'])

    @pytest.mark.django_db
    @override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
    @mock.patch('ansible_base.lib.serializers.mixins.validate_free_text', side_effect=RuntimeError('nh3 crash'))
    def test_unexpected_error_in_json_field_returns_generic_error(self, _mock, caplog):
        data = {'name': 'TestCity', 'extra_data': {'host': 'example.com'}}
        with caplog.at_level(logging.ERROR, logger=MIXIN_LOGGER):
            serializer = CitySerializer(data=data)
            assert not serializer.is_valid()
        assert 'extra_data' in serializer.errors
        assert 'host' in serializer.errors['extra_data']
        assert 'Validation could not be completed' in str(serializer.errors['extra_data']['host'])

    @pytest.mark.django_db
    @override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=False)
    @mock.patch('ansible_base.lib.serializers.mixins.validate_free_text', side_effect=RuntimeError('nh3 crash'))
    def test_unexpected_error_in_json_field_logged_but_passes_when_off(self, _mock, caplog):
        data = {'name': 'TestCity', 'extra_data': {'host': 'example.com'}}
        with caplog.at_level(logging.ERROR, logger=MIXIN_LOGGER):
            serializer = CitySerializer(data=data)
            assert serializer.is_valid(), serializer.errors
        assert any('Unexpected error validating JSON key' in r.message for r in caplog.records)
