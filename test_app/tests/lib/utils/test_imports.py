"""
Tests for ansible_base.lib.utils.imports module.
"""

import pytest

from ansible_base.lib.utils.imports import import_object


@pytest.mark.parametrize(
    "import_path,default_attr,should_be_callable",
    [
        # Full path imports (single argument)
        pytest.param("django.conf.settings", None, False, id="django_settings_object"),
        pytest.param("django.utils.text.slugify", None, True, id="django_slugify_function"),
        pytest.param("django.contrib.auth.models.User", None, True, id="django_user_model_class"),
        pytest.param("ansible_base.lib.utils.imports.import_object", None, True, id="import_object_itself"),
        # Module + attribute imports (two arguments)
        pytest.param("django.conf", "settings", False, id="django_settings_split"),
        pytest.param("django.utils.text", "slugify", True, id="django_slugify_split"),
        pytest.param("django.contrib.auth.models", "User", True, id="django_user_model_split"),
        pytest.param("ansible_base.lib.utils.imports", "import_object", True, id="import_object_split"),
    ],
)
def test_import_object_valid_imports(import_path, default_attr, should_be_callable):
    """Test import_object successfully imports various objects."""
    result = import_object(import_path, default_attr)
    assert result is not None
    if should_be_callable:
        assert callable(result)


@pytest.mark.parametrize(
    "import_path,default_attr,exception_type,error_message_contains",
    [
        # Invalid full paths
        pytest.param(
            "nonexistent_module.SomeClass",
            None,
            ImportError,
            "No module named 'nonexistent_module'",
            id="nonexistent_module_full_path",
        ),
        pytest.param(
            "django.conf.NonExistentSetting",
            None,
            AttributeError,
            "has no attribute 'NonExistentSetting'",
            id="nonexistent_attribute_full_path",
        ),
        pytest.param(
            "nodots",
            None,
            ValueError,
            "Invalid import path",
            id="no_dots_in_path",
        ),
        pytest.param(
            "",
            None,
            ValueError,
            "Invalid import path",
            id="empty_string_full_path",
        ),
        # Invalid split imports
        pytest.param(
            "nonexistent_module",
            "SomeClass",
            ImportError,
            "No module named 'nonexistent_module'",
            id="nonexistent_module_split",
        ),
        pytest.param(
            "django.conf",
            "NonExistentSetting",
            AttributeError,
            "has no attribute 'NonExistentSetting'",
            id="nonexistent_attribute_split",
        ),
    ],
)
def test_import_object_invalid_imports(import_path, default_attr, exception_type, error_message_contains):
    """Test import_object raises appropriate exceptions for invalid imports."""
    with pytest.raises(exception_type) as exc_info:
        import_object(import_path, default_attr)
    assert error_message_contains in str(exc_info.value)


@pytest.mark.parametrize(
    "module_path,attr_name,should_be_callable",
    [
        pytest.param("os", "path", False, id="os_path_module"),
        pytest.param("collections", "OrderedDict", True, id="ordereddict_class"),
        pytest.param("json", "dumps", True, id="json_dumps_function"),
    ],
)
def test_import_object_standard_library(module_path, attr_name, should_be_callable):
    """Test import_object works with Python standard library."""
    result = import_object(module_path, attr_name)
    assert result is not None
    if should_be_callable:
        assert callable(result)


def test_import_object_same_result_both_formats():
    """Test that both invocation formats return the same object."""
    # Import using full path
    result1 = import_object("django.utils.text.slugify")

    # Import using module + attribute
    result2 = import_object("django.utils.text", "slugify")

    # Should be the exact same function object
    assert result1 is result2


def test_import_object_callable_result():
    """Test that imported functions are actually callable."""
    slugify = import_object("django.utils.text.slugify")
    result = slugify("Hello World")
    assert result == "hello-world"


def test_import_object_class_instantiation():
    """Test that imported classes can be instantiated."""
    OrderedDict = import_object("collections", "OrderedDict")
    instance = OrderedDict()
    assert isinstance(instance, dict)


@pytest.mark.parametrize(
    "import_path,default_attr",
    [
        pytest.param("django.conf.settings", None, id="settings_full_path"),
        pytest.param("django.conf", "settings", id="settings_split_path"),
    ],
)
def test_import_object_consistency(import_path, default_attr):
    """Test that import_object returns consistent results across multiple calls."""
    result1 = import_object(import_path, default_attr)
    result2 = import_object(import_path, default_attr)
    result3 = import_object(import_path, default_attr)

    # All three should be the exact same object
    assert result1 is result2 is result3
