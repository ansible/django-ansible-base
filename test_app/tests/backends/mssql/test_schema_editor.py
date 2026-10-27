"""
Tests for custom MS SQL Server SchemaEditor.

Tests the TextField-to-CharField conversion logic.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.db import models
from django.test import TestCase
from mssql.schema import DatabaseSchemaEditor as MSSQLSchemaEditor

from ansible_base.backends.mssql.schema import DatabaseSchemaEditor


def make_schema_editor():
    """Build a schema editor with the connection metadata Django requires."""
    connection = Mock()
    connection.features.can_rollback_ddl = True
    return DatabaseSchemaEditor(connection=connection)


class TestFieldNeedsConversion(TestCase):
    """Test the _field_needs_conversion() logic."""

    def setUp(self):
        """Create a mock schema editor for testing."""
        self.schema_editor = make_schema_editor()

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

    def test_model_without_meta_does_not_need_conversion(self):
        field = models.TextField()

        self.assertFalse(self.schema_editor._field_needs_conversion(field, object))

    def test_non_unique_constraint_and_unrelated_index_do_not_need_conversion(self):
        field = models.TextField()
        field.name = 'test_field'
        constraint = models.CheckConstraint(condition=models.Q(test_field__isnull=False), name='check_test_field')
        index = models.Index(fields=['other_field'], name='idx_other_field')

        class MockModel:
            _meta = type('Meta', (), {'constraints': [constraint], 'indexes': [index]})()

        self.assertFalse(self.schema_editor._field_needs_conversion(field, MockModel))


class TestDetermineMaxLength(TestCase):
    """Test the _determine_max_length() logic."""

    def setUp(self):
        """Create a mock schema editor for testing."""
        self.schema_editor = make_schema_editor()

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
        self.schema_editor = make_schema_editor()

    def test_copies_relevant_attributes(self):
        """Should copy relevant field attributes."""
        field = models.TextField(null=True, blank=True, db_index=True, unique=True, help_text="Test help", verbose_name="Test Field")

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


class TestSchemaEditorConstraints(TestCase):
    def setUp(self):
        self.schema_editor = make_schema_editor()
        self.field = models.TextField(null=True)
        self.field.set_attributes_from_name('description')
        self.model = SimpleNamespace(
            _meta=SimpleNamespace(
                db_table='test_table',
                get_field=lambda field_name: self.field if field_name == 'description' else None,
            )
        )

    def test_add_constraint_converts_existing_nvarchar_max_textfield(self):
        constraint = models.UniqueConstraint(fields=['description'], name='unique_description')
        with (
            patch.object(self.schema_editor, '_get_column_type', return_value='nvarchar(max)') as get_column_type,
            patch.object(self.schema_editor, 'execute') as execute,
            patch.object(MSSQLSchemaEditor, 'add_constraint', return_value='parent result') as add_constraint,
        ):
            result = self.schema_editor.add_constraint(self.model, constraint)

        self.assertEqual(result, 'parent result')
        get_column_type.assert_called_once_with('test_table', 'description')
        execute.assert_called_once_with('ALTER TABLE [test_table] ALTER COLUMN [description] nvarchar(450) NULL')
        self.assertIsInstance(self.field, models.CharField)
        self.assertEqual(self.field.max_length, 450)
        add_constraint.assert_called_once_with(self.model, constraint)

    def test_add_constraint_leaves_bounded_textfield_unchanged(self):
        constraint = models.UniqueConstraint(fields=['description'], name='unique_description')
        with (
            patch.object(self.schema_editor, '_get_column_type', return_value='nvarchar(255)'),
            patch.object(self.schema_editor, 'execute') as execute,
            patch.object(MSSQLSchemaEditor, 'add_constraint', return_value='parent result'),
        ):
            self.schema_editor.add_constraint(self.model, constraint)

        execute.assert_not_called()
        self.assertIsInstance(self.field, models.TextField)

    def test_add_constraint_ignores_non_unique_constraints(self):
        constraint = models.CheckConstraint(condition=models.Q(description__isnull=False), name='check_description')
        with (
            patch.object(self.schema_editor, '_get_column_type') as get_column_type,
            patch.object(self.schema_editor, 'execute') as execute,
            patch.object(MSSQLSchemaEditor, 'add_constraint', return_value='parent result'),
        ):
            self.schema_editor.add_constraint(self.model, constraint)

        get_column_type.assert_not_called()
        execute.assert_not_called()

    def test_add_index_converts_descending_textfield(self):
        index = models.Index(fields=['-description'], name='idx_description')
        with (
            patch.object(self.schema_editor, '_get_column_type', return_value='nvarchar(max)'),
            patch.object(self.schema_editor, 'execute') as execute,
            patch.object(MSSQLSchemaEditor, 'add_index', return_value='parent result') as add_index,
        ):
            result = self.schema_editor.add_index(self.model, index)

        self.assertEqual(result, 'parent result')
        execute.assert_called_once_with('ALTER TABLE [test_table] ALTER COLUMN [description] nvarchar(450) NULL')
        self.assertIsInstance(self.field, models.CharField)
        add_index.assert_called_once_with(self.model, index)
