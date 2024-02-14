from django.db import models
from django.utils.encoding import smart_str


def make_json_safe(value):
    if isinstance(value, (list, dict, str, int, float, bool, type(None))):
        return value

    return smart_str(value)
