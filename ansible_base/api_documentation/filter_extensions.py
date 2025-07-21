from drf_spectacular.extensions import OpenApiFilterExtension
from drf_spectacular.plumbing import build_parameter_type
from drf_spectacular.utils import OpenApiParameter

from ansible_base.rest_filters.rest_framework.field_lookup_backend import FieldLookupBackend
from ansible_base.rest_filters.rest_framework.order_backend import OrderByBackend
from ansible_base.rest_filters.rest_framework.type_filter_backend import TypeFilterBackend


class FieldLookupBackendExtension(OpenApiFilterExtension):
    target_class = FieldLookupBackend

    def get_schema_operation_parameters(self, auto_schema, *args, **kwargs):
        """
        Generate OpenAPI parameters for FieldLookupBackend.

        This filter backend supports field lookups on any model field using Django's
        field lookup syntax (e.g., field__exact, field__contains, field__gt, etc.).
        Since the actual fields depend on the model, we provide generic examples.
        """
        parameters = []

        # Add model-based parameters if model is available
        if self._has_model_queryset(auto_schema):
            model = auto_schema.view.queryset.model
            model_fields = self._get_relevant_model_fields(model)
            parameters.extend(self._create_model_field_parameters(model, model_fields))

        # Add RBAC parameter
        parameters.append(self._create_role_level_parameter())

        return parameters

    def _has_model_queryset(self, auto_schema):
        """Check if the view has a model queryset."""
        return hasattr(auto_schema.view, 'queryset') and auto_schema.view.queryset is not None

    def _get_relevant_model_fields(self, model):
        """Get relevant model fields, excluding complex relationships."""
        model_fields = []
        for field in model._meta.get_fields():
            if self._is_simple_field(field):
                model_fields.append(field.name)
        return model_fields

    def _is_simple_field(self, field):
        """Check if field is a simple field (not many-to-many or one-to-many)."""
        return hasattr(field, 'name') and not field.many_to_many and not (hasattr(field, 'one_to_many') and field.one_to_many)

    def _create_model_field_parameters(self, model, field_names):
        """Create parameters for all model fields."""
        parameters = []
        for field_name in field_names:
            parameters.extend(self._create_field_parameters(model, field_name))
        return parameters

    def _create_field_parameters(self, model, field_name):
        """Create all parameter variations for a single field."""
        parameters = []

        # Basic exact match parameter
        parameters.append(self._create_parameter(field_name, f'Filter by {field_name} (exact match)'))

        # Add field-type specific parameters
        field_obj = self._get_field_by_name(model, field_name)
        if field_obj:
            if self._is_string_field(field_obj):
                parameters.append(self._create_parameter(f'{field_name}__icontains', f'Filter by {field_name} (case-insensitive partial match)'))

            if self._is_numeric_or_date_field(field_obj):
                parameters.extend(self._create_comparison_parameters(field_name))

        return parameters

    def _get_field_by_name(self, model, field_name):
        """Get field object by name from model."""
        for field in model._meta.get_fields():
            if hasattr(field, 'name') and field.name == field_name:
                return field
        return None

    def _is_string_field(self, field):
        """Check if field is a string-based field."""
        from django.db import models

        return isinstance(field, (models.CharField, models.TextField))

    def _is_numeric_or_date_field(self, field):
        """Check if field is numeric or date-based."""
        from django.db import models

        numeric_date_types = (models.IntegerField, models.DateTimeField, models.DateField, models.DecimalField, models.FloatField)
        return isinstance(field, numeric_date_types)

    def _create_comparison_parameters(self, field_name):
        """Create comparison parameters (gt, gte, lt, lte) for a field."""
        parameters = []
        for lookup in ['gt', 'gte', 'lt', 'lte']:
            parameters.append(self._create_parameter(f'{field_name}__{lookup}', f'Filter by {field_name} ({lookup})'))
        return parameters

    def _create_parameter(self, name, description):
        """Create a single OpenAPI parameter."""
        return build_parameter_type(
            name=name,
            schema={'type': 'string'},
            location=OpenApiParameter.QUERY,
            required=False,
            description=description,
        )

    def _create_role_level_parameter(self):
        """Create the role_level parameter for RBAC."""
        return self._create_parameter('role_level', 'Filter by role level for RBAC')


class TypeFilterBackendExtension(OpenApiFilterExtension):
    target_class = TypeFilterBackend

    def get_schema_operation_parameters(self, auto_schema, *args, **kwargs):
        """
        Generate OpenAPI parameters for TypeFilterBackend.

        This filter backend supports filtering by object type.
        """
        return [
            build_parameter_type(
                name='type',
                schema={'type': 'string'},
                location=OpenApiParameter.QUERY,
                required=False,
                description='Filter by object type. Supports comma-separated values for multiple types.',
            )
        ]


class OrderByBackendExtension(OpenApiFilterExtension):
    target_class = OrderByBackend

    def get_schema_operation_parameters(self, auto_schema, *args, **kwargs):
        """
        Generate OpenAPI parameters for OrderByBackend.

        This filter backend supports ordering results by field names.
        """
        parameters = []

        # Add the ordering parameters
        for param_name in ['order', 'order_by']:
            parameters.append(
                build_parameter_type(
                    name=param_name,
                    schema={'type': 'string'},
                    location=OpenApiParameter.QUERY,
                    required=False,
                    description='Order results by field name. Prefix with \'-\' for descending order. Supports comma-separated values for multiple fields.',
                )
            )

        return parameters
