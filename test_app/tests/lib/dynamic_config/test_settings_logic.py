import pytest

from ansible_base.lib.dynamic_config.settings_logic import get_dab_settings

CLEAN_TEXT_POSTPROCESSING_HOOK = "ansible_base.api_documentation.clean_text_schema_hooks.inject_clean_text_pattern_components"


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


def test_api_documentation_registers_clean_text_postprocessing_hook_by_default():
    settings = get_dab_settings(installed_apps=["ansible_base.api_documentation"])

    assert CLEAN_TEXT_POSTPROCESSING_HOOK in settings["SPECTACULAR_SETTINGS"]["POSTPROCESSING_HOOKS"]


def test_api_documentation_appends_clean_text_hook_when_postprocessing_hooks_overridden():
    """Services that override POSTPROCESSING_HOOKS still get the CleanText components hook."""
    custom_hook = "myapp.hooks.custom_postprocess"
    settings = get_dab_settings(
        installed_apps=["ansible_base.api_documentation"],
        spectacular_settings={"POSTPROCESSING_HOOKS": [custom_hook]},
    )

    hooks = settings["SPECTACULAR_SETTINGS"]["POSTPROCESSING_HOOKS"]
    assert hooks == [custom_hook, CLEAN_TEXT_POSTPROCESSING_HOOK]


def test_api_documentation_does_not_duplicate_clean_text_postprocessing_hook():
    settings = get_dab_settings(
        installed_apps=["ansible_base.api_documentation"],
        spectacular_settings={"POSTPROCESSING_HOOKS": [CLEAN_TEXT_POSTPROCESSING_HOOK]},
    )

    hooks = settings["SPECTACULAR_SETTINGS"]["POSTPROCESSING_HOOKS"]
    assert hooks.count(CLEAN_TEXT_POSTPROCESSING_HOOK) == 1
