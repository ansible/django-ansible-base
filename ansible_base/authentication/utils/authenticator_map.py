import re
from typing import Any, Optional

from django.utils.translation import gettext_lazy as _

_EXPANSION_FIELDS = ['organization', 'role', 'team']


def has_expansion(value: Optional[str]) -> bool:
    """
    Checks the given value to see if it has the expansion syntax
    """
    if not value:
        return False
    if re.search(r'{%.*%}', value):
        return True
    else:
        return False


def check_expansion_syntax(value: Optional[str]) -> Optional[Any]:
    """
    Check a given field to see if it contains the proper syntax for {% for_attr_value(user_orgs) %}

    Raises a ValidationError if its incorrect
    """

    if has_expansion(value) and not re.search(r'{%\s*for_attr_value\(.+\)\s*%}', value):
        return _("Expansion only supports the format {% for_attr_value(attribute) %}")
