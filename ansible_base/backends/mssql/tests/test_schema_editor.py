"""
Tests for custom MS SQL Server SchemaEditor.

Tests the TextField-to-CharField conversion logic.
"""

import pytest
from django.db import models
from django.test import TestCase

from ansible_base.backends.mssql.schema import DatabaseSchemaEditor


class TestFieldNeedsConversion(TestCase):
    """Test the _field_needs_conversion() logic."""

    def setUp(self):
        """Create a mock schema editor for testing."""
        # We don't actually need a real connection for these unit tests
        self.schema_editor = DatabaseSchemaEditor(connection=None)

    def test_textfield_with_db_index_needs_conversion(self):
        """TextField with db_index=True should need conversion."""
        field = models.TextField(db_index=True)

        # Create a minimal mock model
        class MockModel:
            _meta = type('Meta', (), {'unique_together': [], 'constraints': [], 'indexes': []})()

        result = self.schema_editor._field_needs_conversion(field, MockModel)
        self.assertTrue(result)

    def test_textfield_with_unique_needs_conversion(self):
        """TextField with unique=True should need conversion."""
        field = models.TextField(unique=True)

        class MockModel:
            _meta = type('Meta', (), {'unique_together': [], 'constraints': [], 'indexes': []})()

        result = self.schema_editor._field_needs_conversion(field, MockModel)
        self.assertTrue(result)

    def test_textfield_in_unique_together_needs_conversion(self):
        """TextField in unique_together should need conversion."""
        field = models.TextField()
        field.name = 'test_field'

        class MockModel:
            _meta = type('Meta', (), {'unique_together': [('test_field', 'other_field')], 'constraints': [], 'indexes': []})()

        result = self.schema_editor._field_needs_conversion(field, MockModel)
        self.assertTrue(result)

    def test_textfield_in_unique_constraint_needs_conversion(self):
        """TextField in UniqueConstraint should need conversion."""
        field = models.TextField()
        field.name = 'test_field'

        constraint = models.UniqueConstraint(fields=['test_field'], name='unique_test')

        class MockModel:
            _meta = type('Meta', (), {'unique_together': [], 'constraints': [constraint], 'indexes': []})()

        result = self.schema_editor._field_needs_conversion(field, MockModel)
        self.assertTrue(result)

    def test_textfield_in_index_needs_conversion(self):
        """TextField in Index should need conversion."""
        field = models.TextField()
        field.name = 'test_field'

        index = models.Index(fields=['test_field'], name='idx_test')

        class MockModel:
            _meta = type('Meta', (), {'unique_together': [], 'constraints': [], 'indexes': [index]})()

        result = self.schema_editor._field_needs_conversion(field, MockModel)
        self.assertTrue(result)

    def test_plain_textfield_does_not_need_conversion(self):
        """Plain TextField without constraints should not need conversion."""
        field = models.TextField()
        field.name = 'test_field'

        class MockModel:
            _meta = type('Meta', (), {'unique_together': [], 'constraints': [], 'indexes': []})()

        result = self.schema_editor._field_needs_conversion(field, MockModel)
        self.assertFalse(result)


class TestDetermineMaxLength(TestCase):
    """Test the _determine_max_length() logic."""

    def setUp(self):
        """Create a mock schema editor for testing."""
        self.schema_editor = DatabaseSchemaEditor(connection=None)

    def test_codename_field_gets_100(self):
        """Codename fields should get max_length=100."""
        field = models.TextField()
        field.name = 'codename'

        class MockModel:
            _meta = type('Meta', (), {'label': 'test.Model'})()

        result = self.schema_editor._determine_max_length(field, MockModel)
        self.assertEqual(result, 100)

    def test_object_id_field_gets_450(self):
        """object_id fields should get max_length=450."""
        field = models.TextField()
        field.name = 'object_id'

        class MockModel:
            _meta = type('Meta', (), {'label': 'test.Model'})()

        result = self.schema_editor._determine_max_length(field, MockModel)
        self.assertEqual(result, 450)

    def test_parent_reference_field_gets_450(self):
        """parent_reference fields should get max_length=450."""
        field = models.TextField()
        field.name = 'parent_reference'

        class MockModel:
            _meta = type('Meta', (), {'label': 'test.Model'})()

        result = self.schema_editor._determine_max_length(field, MockModel)
        self.assertEqual(result, 450)

    def test_name_field_gets_255(self):
        """name fields should get max_length=255."""
        field = models.TextField()
        field.name = 'name'

        class MockModel:
            _meta = type('Meta', (), {'label': 'test.Model'})()

        result = self.schema_editor._determine_max_length(field, MockModel)
        self.assertEqual(result, 255)

    def test_singleton_name_field_gets_64(self):
        """singleton_name fields should get max_length=64."""
        field = models.TextField()
        field.name = 'singleton_name'

        class MockModel:
            _meta = type('Meta', (), {'label': 'test.Model'})()

        result = self.schema_editor._determine_max_length(field, MockModel)
        self.assertEqual(result, 64)

    def test_role_field_gets_64(self):
        """role_field fields should get max_length=64."""
        field = models.TextField()
        field.name = 'role_field'

        class MockModel:
            _meta = type('Meta', (), {'label': 'test.Model'})()

        result = self.schema_editor._determine_max_length(field, MockModel)
        self.assertEqual(result, 64)

    def test_unknown_field_gets_450_default(self):
        """Unknown fields should get default max_length=450."""
        field = models.TextField()
        field.name = 'some_random_field'

        class MockModel:
            _meta = type('Meta', (), {'label': 'test.Model'})()

        result = self.schema_editor._determine_max_length(field, MockModel)
        self.assertEqual(result, 450)


class TestCopyFieldAttrs(TestCase):
    """Test the _copy_field_attrs() logic."""

    def setUp(self):
        """Create a mock schema editor for testing."""
        self.schema_editor = DatabaseSchemaEditor(connection=None)

    def test_copies_relevant_attributes(self):
        """Should copy relevant field attributes."""
        field = models.TextField(
            null=True, blank=True, db_index=True, unique=True, help_text="Test help", verbose_name="Test Field"
        )

        attrs = self.schema_editor._copy_field_attrs(field)

        self.assertTrue(attrs['null'])
        self.assertTrue(attrs['blank'])
        self.assertTrue(attrs['db_index'])
        self.assertTrue(attrs['unique'])
        self.assertEqual(attrs['help_text'], "Test help")
        self.assertEqual(attrs['verbose_name'], "Test Field")

    def test_does_not_copy_max_length(self):
        """Should not copy max_length from TextField (it doesn't have one anyway)."""
        field = models.TextField(help_text="Test")

        attrs = self.schema_editor._copy_field_attrs(field)

        self.assertNotIn('max_length', attrs)

    def test_skips_default_values(self):
        """Should skip default values to keep field definition clean."""
        field = models.TextField(null=False, blank=False, editable=True)

        attrs = self.schema_editor._copy_field_attrs(field)

        # These should not be in attrs since they're defaults
        self.assertNotIn('null', attrs)
        self.assertNotIn('blank', attrs)
        self.assertNotIn('editable', attrs)
