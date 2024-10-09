import logging
import os

from django import template
from django.conf import settings
from django.utils.safestring import mark_safe

logger = logging.getLogger("ansible_base.lib.templatetags.util")
register = template.Library()


@register.simple_tag
def inline_file(relative_path, is_safe=False, fatal=False):
    path = os.path.join(settings.BASE_DIR, relative_path)
    try:
        with open(path, 'r') as file:
            contents = file.read()
            if is_safe:
                contents = mark_safe(contents)
            return contents
    except Exception:
        logger.exception(f"Failed to read file {path}")
        if fatal:
            raise
