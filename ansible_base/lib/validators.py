import re
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

# Tier 1: strict name allowlist
resource_name_validator = RegexValidator(
    regex=r'^[\w][\w .@-]*$',
    message=_('May only contain letters, numbers, spaces, hyphens, '
              'underscores, dots, and @.'),
    flags=re.UNICODE,
)

# Tier 2: dangerous pattern blocklist
DANGEROUS_PATTERNS = re.compile(
    r'<[a-zA-Z/!]'        # HTML tags
    r'|javascript\s*:'     # JS protocol
    r'|\bon\w{3,}\s*='    # Event handlers
    r'|\$\('              # Shell substitution
    r'|`'                  # Backtick execution
    r'|\x00'              # Null bytes
    r'|\x1b',             # ANSI escapes
    re.IGNORECASE,
)

# Fields that get Tier 1 instead of Tier 2
DEFAULT_NAME_FIELDS = frozenset({'name', 'username', 'hostname'})


class CleanTextMixin:
    """
    Drop into any ModelSerializer to auto-reject invalid characters
    in text fields. Grandfathers existing values on update.

    Tier 1 (name fields): strict character allowlist
    Tier 2 (all other text fields): dangerous pattern blocklist
    """
    name_fields = DEFAULT_NAME_FIELDS

    def validate(self, attrs):
        model = self.Meta.model
        text_fields = [
            f.name for f in model._meta.get_fields()
            if hasattr(f, 'get_internal_type')
            and f.get_internal_type() in ('CharField', 'TextField')
        ]

        errors = {}
        for field_name in text_fields:
            if field_name not in attrs:
                continue
            value = attrs[field_name]
            if not isinstance(value, str):
                continue

            # On update, skip if value hasn't changed (grandfather)
            if self.instance and getattr(
                self.instance, field_name, None
            ) == value:
                continue

            # Apply appropriate validator based on field type
            if field_name in self.name_fields:
                try:
                    resource_name_validator(value)
                except Exception:
                    errors[field_name] = resource_name_validator.message
            else:
                if DANGEROUS_PATTERNS.search(value):
                    errors[field_name] = _(
                        'Contains potentially unsafe content.'
                    )

        if errors:
            raise serializers.ValidationError(errors)

        return super().validate(attrs)
