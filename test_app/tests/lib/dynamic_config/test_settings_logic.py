import pytest

from ansible_base.lib.dynamic_config.settings_logic import get_dab_settings


@pytest.mark.parametrize(
    "caches,expect_exception",
    [
        ({}, False),
        ({"default": {"BACKEND": "junk"}}, False),
        ({"default": {"BACKEND": "not_ansible_base.lib.cache.fallback_cache.DABCacheWithFallback"}}, True),
        ({"default": {"BACKEND": "ansible_base.lib.cache.fallback_cache.DABCacheWithFallback"}}, True),
        ({"default": {"BACKEND": "ansible_base.lib.cache.fallback_cache.DABCacheWithFallback"}, "primary": {}}, True),
        ({"default": {"BACKEND": "ansible_base.lib.cache.fallback_cache.DABCacheWithFallback"}, "fallback": {}}, True),
        ({"default": {"BACKEND": "ansible_base.lib.cache.fallback_cache.DABCacheWithFallback"}, "primary": {}, "fallback": {}}, False),
    ],
)
def test_cache_settings(caches, expect_exception):
    try:
        get_dab_settings(installed_apps=[], caches=caches)
    except RuntimeError:
        if not expect_exception:
            raise


def test_api_documentation_uses_dab_docstring_exclusions():
    settings = get_dab_settings(installed_apps=["ansible_base.api_documentation"])

    assert settings["SPECTACULAR_SETTINGS"]["GET_LIB_DOC_EXCLUDES"] == ("ansible_base.api_documentation.customizations.get_dab_lib_doc_excludes")
