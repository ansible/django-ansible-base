from django.utils.encoding import smart_str


def make_json_safe(value):
    if isinstance(value, (list, dict, str, int, float, bool, type(None))):
        return value

    return smart_str(value)


def is_empty(value, check_stripped=True):
    if check_stripped:
        return value is None or str(value).strip() == ''
    else:
        return value is None or str(value) == ''
