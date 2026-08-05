# Generated with AI assistance: Claude Code (Anthropic)
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

validate_resource_name = RegexValidator(
    regex=r'^[\w][\w .@-]{0,511}\Z',
    message=_(
        "Enter a valid resource name. Must start with a letter, digit, or underscore."
        " After the first character, spaces, dots, @, and hyphens are also allowed."
        " Maximum length is 512 characters."
        " Special characters like <, >, &, |, ;, ', \", $, and path separators are not permitted."
    ),
    code="invalid_resource_name",
)
