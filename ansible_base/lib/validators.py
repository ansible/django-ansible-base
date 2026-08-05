import re
import unicodedata

from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

# Tier 1: strict name allowlist
# ^[\w]       — must start with a Unicode letter, digit, or underscore
# [\w .@-]*   — remaining: Unicode letters/digits/underscore, space, period, @, hyphen
# \Z          — absolute end of string (no trailing newline bypass)
resource_name_validator = RegexValidator(
    regex=r'^[\w][\w .@-]*\Z',
    message=_('May only contain letters, numbers, spaces, hyphens, '
              'underscores, dots, and @.'),
    flags=re.UNICODE,
)

# Tier 2: dangerous pattern blocklist
DANGEROUS_PATTERNS = re.compile(
    r'[\x00-\x08\x0b\x0c\x0d-\x1f\x7f-\x9f]'          # Control characters
    r'|<\s*/?(?:script|iframe|object|embed|form'
    r'|base|meta|link|svg|math|template)\b'              # Dangerous HTML tags
    r'|\bon[a-z]{3,}\s*='                                # Event handlers
    r'|\b(?:javascript|vbscript|data)\s*:'               # Dangerous URI schemes
    r'|\$\([^)]+\)|\$\{[^}]+\}',                        # Shell/template substitution
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

    Configurable attributes:
        name_fields: field names routed to Tier 1 (allowlist).
        excluded_fields: field names skipped entirely (no validation).
            Use for fields that legitimately contain HTML, template syntax,
            or other structured content (e.g. Jinja2 templates, custom
            login HTML).
    """
    name_fields = DEFAULT_NAME_FIELDS
    excluded_fields = frozenset()

    def validate(self, attrs):
        model = self.Meta.model
        # We use get_internal_type() rather than isinstance() here deliberately.
        # isinstance(f, (CharField, TextField)) would also catch SlugField and
        # URLField — format-constrained subclasses that have their own validators
        # and are not free-text fields per ANSTRAT-1756. Those subclasses override
        # get_internal_type() to return their own name (e.g. "SlugField"), so they
        # are naturally excluded by this check. Custom free-text subclasses (e.g.
        # EncryptedTextField) typically do NOT override get_internal_type(), so they
        # inherit "CharField"/"TextField" and are caught here automatically.
        text_fields = [
            f.name for f in model._meta.get_fields()
            if hasattr(f, 'get_internal_type')
            and f.get_internal_type() in ('CharField', 'TextField')
        ]

        errors = {}
        for field_name in text_fields:
            if field_name in self.excluded_fields:
                continue
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
                    resource_name_validator(unicodedata.normalize('NFC', value))
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
