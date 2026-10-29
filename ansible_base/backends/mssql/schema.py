"""
Custom MS SQL Server SchemaEditor for TextField compatibility.

Automatically converts TextField to CharField when indexes or unique constraints
are detected, enabling MS SQL Server compatibility without modifying migrations.
"""

import logging

from django.core.exceptions import FieldDoesNotExist
from django.db import models
from mssql.schema import DatabaseSchemaEditor as MSSQLSchemaEditor

from ansible_base.lib.utils.mssql import get_mssql_constrained_textfield_max_length, get_mssql_textfield_max_length

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

    def alter_field(self, model, old_field, new_field, strict=False):
        """Bound an existing TextField before AlterField creates a new index or unique constraint."""
        if self._field_needs_conversion(new_field, model):
            self._convert_existing_textfield_column(model, old_field.name)

        return super().alter_field(model, old_field, new_field, strict)

    def alter_unique_together(self, model, old_unique_together, new_unique_together):
        """Bound existing TextFields before AlterUniqueTogether creates constraints."""
        old_sets = {tuple(fields) for fields in old_unique_together}
        new_sets = {tuple(fields) for fields in new_unique_together}
        for field_names in new_sets.difference(old_sets):
            for field_name in field_names:
                self._convert_existing_textfield_column(model, field_name)

        return super().alter_unique_together(model, old_unique_together, new_unique_together)

    def alter_index_together(self, model, old_index_together, new_index_together):
        """Bound existing TextFields before AlterIndexTogether creates indexes."""
        old_sets = {tuple(fields) for fields in old_index_together}
        new_sets = {tuple(fields) for fields in new_index_together}
        for field_names in new_sets.difference(old_sets):
            for field_name in field_names:
                self._convert_existing_textfield_column(model, field_name)

        return super().alter_index_together(model, old_index_together, new_index_together)

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
        if column_type is None:
            raise RuntimeError(f"Could not find SQL Server column '{table_name}.{column_name}' before adding an index or constraint.")
        if 'max' not in column_type.lower():
            return

        max_length = self._determine_max_length(field, model)
        null_clause = "NULL" if field.null else "NOT NULL"
        sql = f"ALTER TABLE [{table_name}] ALTER COLUMN [{column_name}] nvarchar({max_length}) {null_clause}"
        self.execute(sql)

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
                cursor.execute(
                    """
                    SELECT DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_NAME = %s AND COLUMN_NAME = %s
                """,
                    (table_name, column_name),
                )
                row = cursor.fetchone()
        except Exception as exc:
            raise RuntimeError(f"Could not inspect SQL Server column '{table_name}.{column_name}'.") from exc

        if row is None:
            return None
        data_type, max_length = row
        if max_length == -1:
            return f"{data_type}(max)"
        if max_length:
            return f"{data_type}({max_length})"
        return data_type

    def _field_needs_conversion(self, field, model):
        """
        Check if TextField has db_index, unique, or is in constraints.

        Args:
            field: The Django model field to check
            model: The Django model containing this field

        Returns:
            bool: True if the TextField needs conversion to CharField
        """
        return get_mssql_constrained_textfield_max_length(field, model) is not None

    def _determine_max_length(self, field, model):
        """
        Intelligent max_length selection based on field name and usage.

        Args:
            field: The Django model field
            model: The Django model containing this field

        Returns:
            int: Appropriate max_length for the CharField
        """
        return get_mssql_textfield_max_length(field.name)

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
