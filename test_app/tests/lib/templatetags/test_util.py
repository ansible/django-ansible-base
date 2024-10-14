import pytest
from django.utils.safestring import SafeString

from ansible_base.lib.templatetags.util import inline_file


@pytest.mark.parametrize(
    "path,is_safe,fatal",
    [
        ("test_app/static/test_templatetags_util_inline_file.css", True, False),
        ("test_app/static/test_templatetags_util_inline_file.css", False, False),
        ("test_app/static/does_not_exist.css", True, True),
        ("test_app/static/does_not_exist.css", False, True),
    ],
)
def test_inline_file(path, is_safe, fatal):
    if 'does_not_exist' in path:
        if fatal:
            with pytest.raises(FileNotFoundError):
                inline_file(path, is_safe, fatal)
        else:
            assert inline_file(path, is_safe, fatal) is None
    else:
        result = inline_file(path, is_safe, fatal)
        assert "div > p.foo" in result
        if is_safe:
            assert isinstance(result, SafeString)
        else:
            assert isinstance(result, str)
