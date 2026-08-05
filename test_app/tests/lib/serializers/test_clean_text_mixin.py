import pytest
from rest_framework import serializers

from ansible_base.lib.serializers.mixins import CleanTextMixin
from test_app.models import Organization


class OrgSerializer(CleanTextMixin, serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ['name', 'description', 'extra_field']


class OrgSerializerWithExclusions(CleanTextMixin, serializers.ModelSerializer):
    excluded_fields = frozenset({'description'})

    class Meta:
        model = Organization
        fields = ['name', 'description', 'extra_field']


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
            'onerror=alert(1)',
            'onclick=doEvil()',
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
            'onerror-handler',
            'onclick-handler',
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
    def test_safe_html_entities_accepted(self):
        data = {'name': 'Org', 'description': 'Use <b>bold</b> and <em>emphasis</em>'}
        serializer = OrgSerializer(data=data)
        assert serializer.is_valid(), serializer.errors


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


class TestCleanTextMixinEdgeCases:
    """Edge cases: non-string values, missing fields, partial updates."""

    @pytest.mark.django_db
    def test_non_string_field_skipped(self):
        """Non-string attrs (e.g. None) should not cause errors."""
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
