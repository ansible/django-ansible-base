"""
Custom MS SQL Server SchemaEditor for TextField compatibility.

Automatically converts TextField to CharField when indexes or unique constraints
are detected, enabling MS SQL Server compatibility without modifying migrations.
"""

import logging

from django.core.exceptions import FieldDoesNotExist
from django.db import models
from mssql.schema import DatabaseSchemaEditor as MSSQLSchemaEditor

logger = logging.getLogger('ansible_base.backends.mssql.schema')


class DatabaseSchemaEditor(MSSQLSchemaEditor):
    """
    Custom schema editor that converts TextField to CharField when indexes
    or unique constraints are detected.

    MS SQL Server cannot create indexes or unique constraints on nvarchar(max)
    columns (which is what Django's TextField maps to). This SchemaEditor
    intercepts field SQL generation and dynamically converts problematic
    TextField definitions to CharField with appropriate max_length values.
    """

    def create_model(self, model):
        """
        Override to convert TextField definitions before creating the table.
        """
        # Convert TextFields with constraints to CharFields before creating table
        for field in model._meta.local_fields:
            if isinstance(field, models.TextField) and self._field_needs_conversion(field, model):
                max_length = self._determine_max_length(field, model)

                # Replace the field with a CharField
                # We need to modify the field in-place
                field.__class__ = models.CharField
                field.max_length = max_length

        # Call parent implementation with potentially modified fields
        return super().create_model(model)

    def add_index(self, model, index):
        """
        Override to convert TextFields to CharFields before adding index.

        MS SQL Server cannot create indexes on nvarchar(max) columns.

        Note: If table was created via create_model(), the column is already
        the correct type. We only need to ALTER if the table existed beforehand.
        """
        # Convert indexed TextFields before asking SQL Server to create the index.
        for field_name in index.fields:
            self._convert_existing_textfield_column(model, field_name)

        return super().add_index(model, index)

    def add_constraint(self, model, constraint):
        """
        Override to convert TextFields to CharFields before adding constraint.

        MS SQL Server cannot create unique constraints on nvarchar(max) columns.

        Note: If table was created via create_model(), the column is already
        the correct type. We only need to ALTER if the table existed beforehand.
        """
        # Only handle UniqueConstraints
        if isinstance(constraint, models.UniqueConstraint):
            for field_name in constraint.fields:
                self._convert_existing_textfield_column(model, field_name)

        return super().add_constraint(model, constraint)

    def _convert_existing_textfield_column(self, model, field_name):
        """Bound an existing nvarchar(max) TextField before indexing it."""
        if hasattr(field_name, 'name'):
            field_name = field_name.name
        field_name = field_name.lstrip('-')

        try:
            field = model._meta.get_field(field_name)
        except FieldDoesNotExist:
            return

        if not isinstance(field, models.TextField):
            return

        table_name = model._meta.db_table
        column_name = field.column
        column_type = self._get_column_type(table_name, column_name)
        if not column_type or 'max' not in column_type.lower():
            return

        max_length = self._determine_max_length(field, model)
        null_clause = "NULL" if field.null else "NOT NULL"
        sql = f"ALTER TABLE [{table_name}] ALTER COLUMN [{column_name}] nvarchar({max_length}) {null_clause}"
        self.execute(sql)

        field.__class__ = models.CharField
        field.max_length = max_length

    def column_sql(self, model, field, include_default=False):
        """
        Override to intercept TextField with constraints.

        For MS SQL Server, TextField maps to nvarchar(max) which cannot be:
        - Indexed (db_index=True)
        - Made unique (unique=True)
        - Used in unique constraints
        - Used in indexes

        When we detect these cases, we convert TextField to CharField with
        an appropriate max_length.
        """
        # Only process TextField instances
        if isinstance(field, models.TextField):
            if self._field_needs_conversion(field, model):
                logger.warning(
                    f"Converting TextField to CharField for {model._meta.label}.{field.name} "
                    f"(db_index={getattr(field, 'db_index', False)}, "
                    f"unique={getattr(field, 'unique', False)})"
                )

                # Determine appropriate max_length
                max_length = self._determine_max_length(field, model)

                # Create a CharField with the same attributes
                converted_field = models.CharField(max_length=max_length, **self._copy_field_attrs(field))

                # Generate SQL for CharField instead
                return super().column_sql(model, converted_field, include_default)

        # Default behavior for all other fields and unconverted TextFields
        return super().column_sql(model, field, include_default)

    def _get_column_type(self, table_name, column_name):
        """
        Query the actual column type from the database.

        Returns column type string like 'nvarchar(450)' or 'nvarchar(max)', or None if column doesn't exist.
        """
        try:
            with self.connection.cursor() as cursor:
                # Use %s placeholders with tuple for parameters
                cursor.execute(
                    """
                    SELECT DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_NAME = %s AND COLUMN_NAME = %s
                """,
                    (table_name, column_name),
                )
                row = cursor.fetchone()
                if row:
                    data_type, max_length = row
                    if max_length == -1:
                        return f"{data_type}(max)"
                    elif max_length:
                        return f"{data_type}({max_length})"
                    else:
                        return data_type
                return None
        except Exception:
            return None

    def _field_needs_conversion(self, field, model):
        """
        Check if TextField has db_index, unique, or is in constraints.

        Args:
            field: The Django model field to check
            model: The Django model containing this field

        Returns:
            bool: True if the TextField needs conversion to CharField
        """
        if getattr(field, 'db_index', False) or getattr(field, 'unique', False):
            return True

        model_meta = getattr(model, '_meta', None)
        if model_meta is None:
            return False

        field_name = field.name
        return (
            self._field_in_unique_together(field_name, model_meta)
            or self._field_in_unique_constraints(field_name, model_meta)
            or self._field_in_indexes(field_name, model_meta)
        )

    @staticmethod
    def _field_in_unique_together(field_name, model_meta):
        return any(field_name in fields for fields in getattr(model_meta, 'unique_together', []))

    @staticmethod
    def _field_in_unique_constraints(field_name, model_meta):
        return any(
            isinstance(constraint, models.UniqueConstraint) and field_name in getattr(constraint, 'fields', [])
            for constraint in getattr(model_meta, 'constraints', [])
        )

    @staticmethod
    def _field_in_indexes(field_name, model_meta):
        return any(field_name in getattr(index, 'fields', []) for index in getattr(model_meta, 'indexes', []))

    def _determine_max_length(self, field, model):
        """
        Intelligent max_length selection based on field name and usage.

        Args:
            field: The Django model field
            model: The Django model containing this field

        Returns:
            int: Appropriate max_length for the CharField
        """
        field_name = field.name.lower()

        # Permission codenames: Django standard is 100
        if 'codename' in field_name:
            return 100

        # Object IDs and parent references: MS SQL index limit
        # MS SQL can index up to 900 bytes, nvarchar uses 2 bytes per char
        if any(x in field_name for x in ['object_id', 'parent_reference']):
            return 450

        # Names: standard varchar length (common in eda-server, awx)
        if field_name == 'name':
            return 255

        # Singleton names and role fields: shorter (awx-specific)
        if any(x in field_name for x in ['singleton', 'role_field']):
            return 64

        # Default: MS SQL index limit (safe for all constrained TextFields)
        return 450

    def _copy_field_attrs(self, field):
        """
        Copy relevant attributes from original TextField to converted CharField.

        Args:
            field: The original TextField

        Returns:
            dict: Attributes to pass to CharField constructor
        """
        attrs = {}

        # Attributes to copy (exclude max_length from TextField)
        copy_attrs = [
            'null',
            'blank',
            'default',
            'db_index',
            'unique',
            'verbose_name',
            'help_text',
            'validators',
            'editable',
            'choices',
            'db_column',
            'db_tablespace',
            'error_messages',
        ]

        for attr in copy_attrs:
            if hasattr(field, attr):
                value = getattr(field, attr)
                # Don't copy if it's the default value to keep the field definition clean
                if attr == 'null' and value is False:
                    continue
                if attr == 'blank' and value is False:
                    continue
                if attr == 'editable' and value is True:
                    continue
                attrs[attr] = value

        return attrs
