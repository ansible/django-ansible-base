"""
Custom MS SQL Server SchemaEditor for TextField compatibility.

Automatically converts TextField to CharField when indexes or unique constraints
are detected, enabling MS SQL Server compatibility without modifying migrations.
"""

import logging
import sys

from django.db import models
from mssql.schema import DatabaseSchemaEditor as MSSQLSchemaEditor

logger = logging.getLogger('ansible_base.backends.mssql.schema')

# Module-level print to confirm this module is being loaded
print("[CUSTOM SCHEMA MODULE] ansible_base.backends.mssql.schema loaded!", file=sys.stderr)


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
        print(f"[CUSTOM SCHEMA] create_model called for {model._meta.label}", file=sys.stderr)

        # Convert TextFields with constraints to CharFields before creating table
        for field in model._meta.local_fields:
            if isinstance(field, models.TextField) and self._field_needs_conversion(field, model):
                print(f"[CUSTOM SCHEMA] ✓ Converting {field.name} before table creation", file=sys.stderr)
                max_length = self._determine_max_length(field, model)

                # Replace the field with a CharField
                # We need to modify the field in-place
                field.__class__ = models.CharField
                field.max_length = max_length

        # Call parent implementation with potentially modified fields
        return super().create_model(model)

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
        print(f"[CUSTOM SCHEMA] column_sql called for {model._meta.label}.{field.name} (type: {type(field).__name__})", file=sys.stderr)
        logger.info(f"column_sql called for {model._meta.label}.{field.name} (type: {type(field).__name__})")

        # Only process TextField instances
        if isinstance(field, models.TextField):
            if self._field_needs_conversion(field, model):
                print(f"[CUSTOM SCHEMA] ✓ Converting TextField to CharField for {model._meta.label}.{field.name}", file=sys.stderr)
                logger.warning(
                    f"Converting TextField to CharField for {model._meta.label}.{field.name} "
                    f"(db_index={getattr(field, 'db_index', False)}, "
                    f"unique={getattr(field, 'unique', False)})"
                )

                # Determine appropriate max_length
                max_length = self._determine_max_length(field, model)

                # Create a CharField with the same attributes
                converted_field = models.CharField(
                    max_length=max_length, **self._copy_field_attrs(field)
                )

                print(f"[CUSTOM SCHEMA] → Converting to CharField(max_length={max_length})", file=sys.stderr)

                # Generate SQL for CharField instead
                return super().column_sql(model, converted_field, include_default)
            else:
                print(f"[CUSTOM SCHEMA] ✗ TextField {field.name} does not need conversion", file=sys.stderr)

        # Default behavior for all other fields and unconverted TextFields
        return super().column_sql(model, field, include_default)

    def _field_needs_conversion(self, field, model):
        """
        Check if TextField has db_index, unique, or is in constraints.

        Args:
            field: The Django model field to check
            model: The Django model containing this field

        Returns:
            bool: True if the TextField needs conversion to CharField
        """
        # Check direct field attributes
        if getattr(field, 'db_index', False):
            logger.debug(f"Field {field.name} needs conversion: db_index=True")
            return True

        if getattr(field, 'unique', False):
            logger.debug(f"Field {field.name} needs conversion: unique=True")
            return True

        # Check model Meta constraints and indexes
        if hasattr(model, '_meta'):
            # Check legacy unique_together
            for unique_fields in getattr(model._meta, 'unique_together', []):
                if field.name in unique_fields:
                    logger.debug(f"Field {field.name} needs conversion: in unique_together")
                    return True

            # Check UniqueConstraint in Meta.constraints
            for constraint in getattr(model._meta, 'constraints', []):
                if isinstance(constraint, models.UniqueConstraint):
                    # Handle both field names and F() expressions
                    constraint_fields = getattr(constraint, 'fields', [])
                    if field.name in constraint_fields:
                        logger.debug(f"Field {field.name} needs conversion: in UniqueConstraint")
                        return True

            # Check indexes in Meta.indexes
            for index in getattr(model._meta, 'indexes', []):
                # Handle both field names and F() expressions
                index_fields = getattr(index, 'fields', [])
                if field.name in index_fields:
                    logger.debug(f"Field {field.name} needs conversion: in Index")
                    return True

        return False

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
        logger.debug(f"Using default max_length=450 for {model._meta.label}.{field.name}")
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
