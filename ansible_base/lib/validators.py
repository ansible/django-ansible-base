import re

from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

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
