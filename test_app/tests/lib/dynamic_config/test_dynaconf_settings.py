from dynaconf import ValidationError, Validator

from ansible_base.lib.dynamic_config import (
    export,
    factory,
    load_envvars,
    load_python_file_with_injected_context,
    load_standard_settings_files,
    toggle_feature_flags,
    validate,
)


def test_swagger_disabled():
    settings = factory("", "TEST", INSTALLED_APPS=[])
    assert 'drf_spectacular' not in settings['INSTALLED_APPS']


def test_swagger_enabled():
    settings = factory("", "TEST", INSTALLED_APPS=['ansible_base.api_documentation'])
    assert 'drf_spectacular' in settings['INSTALLED_APPS']
    assert "DEFAULT_SCHEMA_CLASS" in settings['REST_FRAMEWORK']

    assert "TITLE" in settings['SPECTACULAR_SETTINGS']
    assert "DESCRIPTION" in settings['SPECTACULAR_SETTINGS']
    assert "VERSION" in settings['SPECTACULAR_SETTINGS']
    assert "SCHEMA_PATH_PREFIX" in settings['SPECTACULAR_SETTINGS']


def test_authentication_with_backends():
    settings = factory(
        "",
        "TEST",
        AUTHENTICATION_BACKENDS=['something'],
        INSTALLED_APPS=['ansible_base.authentication'],
    )
    assert "social_django" in settings['INSTALLED_APPS']
    assert 'ansible_base.authentication.backend.AnsibleBaseAuth' in settings['AUTHENTICATION_BACKENDS']
    assert 'ansible_base.authentication.middleware.AuthenticatorBackendMiddleware' in settings['MIDDLEWARE']
    assert 'ansible_base.authentication.session.SessionAuthentication' in settings['REST_FRAMEWORK']['DEFAULT_AUTHENTICATION_CLASSES']
    assert 'ansible_base.authentication.authenticator_plugins' in settings['ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIXES']
    assert 'SOCIAL_AUTH_LOGIN_REDIRECT_URL' in settings
    assert "SOCIAL_AUTH_PIPELINE" in settings
    assert "SOCIAL_AUTH_STORAGE" in settings
    assert "SOCIAL_AUTH_STRATEGY" in settings
    assert "SOCIAL_AUTH_LOGIN_REDIRECT_URL" in settings


def test_authentication_no_backends():
    settings = factory("", "TEST", INSTALLED_APPS=['ansible_base.authentication'])
    assert 'ansible_base.authentication.backend.AnsibleBaseAuth' in settings['AUTHENTICATION_BACKENDS']


def test_append_middleware():
    settings = factory("", "TEST", INSTALLED_APPS=['ansible_base.authentication'], REST_FRAMEWORK={}, MIDDLEWARE=['something'])
    assert 'ansible_base.authentication.middleware.AuthenticatorBackendMiddleware' == settings['MIDDLEWARE'][-1]


def test_insert_middleware():
    settings = factory(
        "", "TEST", INSTALLED_APPS=['ansible_base.authentication'], MIDDLEWARE=['something', 'django.contrib.auth.middleware.AuthenticationMiddleware', 'else']
    )
    assert 'ansible_base.authentication.middleware.AuthenticatorBackendMiddleware' == settings['MIDDLEWARE'][2]


def test_dont_update_class_prefixes():
    settings = factory("", "TEST", INSTALLED_APPS=['ansible_base.authentication'], ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIXES=['other.things'])
    assert 'ansible_base.authentication.authenticator_plugins' not in settings['ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIXES']


def test_filtering():
    settings = factory("", "TEST", INSTALLED_APPS=['ansible_base.rest_filters'], REST_FRAMEWORK={'something': 'else'})
    assert 'ansible_base.rest_filters.rest_framework.type_filter_backend.TypeFilterBackend' in settings['REST_FRAMEWORK']['DEFAULT_FILTER_BACKENDS']
    assert 'something' in settings['REST_FRAMEWORK']


def test_rbac_required_settings():
    settings = factory("", "TEST", INSTALLED_APPS=['ansible_base.rbac'])
    rbac_expected_settings = [
        'ANSIBLE_BASE_MANAGED_ROLE_REGISTRY',
        'ANSIBLE_BASE_CREATOR_DEFAULTS',
        'ANSIBLE_BASE_CHECK_RELATED_PERMISSIONS',
        'ANSIBLE_BASE_ROLE_CREATOR_NAME',
        'ANSIBLE_BASE_ROLES_REQUIRE_VIEW',
        'ANSIBLE_BASE_DELETE_REQUIRE_CHANGE',
        'ANSIBLE_BASE_ALLOW_TEAM_PARENTS',
        'ANSIBLE_BASE_ALLOW_TEAM_ORG_PERMS',
        'ANSIBLE_BASE_ALLOW_TEAM_ORG_MEMBER',
        'ANSIBLE_BASE_ALLOW_TEAM_ORG_ADMIN',
        'ANSIBLE_BASE_ALLOW_CUSTOM_ROLES',
        'ANSIBLE_BASE_ALLOW_CUSTOM_TEAM_ROLES',
        'ANSIBLE_BASE_ALLOW_SINGLETON_USER_ROLES',
        'ANSIBLE_BASE_ALLOW_SINGLETON_TEAM_ROLES',
        'ANSIBLE_BASE_ALLOW_SINGLETON_ROLES_API',
        'ANSIBLE_BASE_EVALUATIONS_IGNORE_CONFLICTS',
        'ANSIBLE_BASE_BYPASS_SUPERUSER_FLAGS',
        'ANSIBLE_BASE_BYPASS_ACTION_FLAGS',
        'ANSIBLE_BASE_CACHE_PARENT_PERMISSIONS',
        'ALLOW_LOCAL_RESOURCE_MANAGEMENT',
        'ALLOW_LOCAL_ASSIGNING_JWT_ROLES',
        'ALLOW_SHARED_RESOURCE_CUSTOM_ROLES',
        'MANAGE_ORGANIZATION_AUTH',
        'ANSIBLE_BASE_RBAC_MODEL_REGISTRY',
        'ORG_ADMINS_CAN_SEE_ALL_USERS',
    ]
    assert set(rbac_expected_settings) == set(settings.keys() & rbac_expected_settings)


def test_resource_registry_required_settings():
    settings = factory("", "TEST", INSTALLED_APPS=['ansible_base.resource_registry'])
    resource_registry_expected_settings = [
        'RESOURCE_SERVER_SYNC_ENABLED',
        'RESOURCE_SERVICE_PATH',
        'ENABLE_SERVICE_BACKED_SSO',
    ]
    assert set(resource_registry_expected_settings) == set(settings.keys() & resource_registry_expected_settings)


def test_export():
    """Assert export function sets variables back to module object"""
    settings = factory("", "TEST")
    settings.set("KEY", 123)

    class FakeModule: ...  # noqa: E701

    fake_module = FakeModule()
    export(fake_module, settings)
    assert fake_module.KEY == 123


def test_load_envvars(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "123")
    settings = factory("", "TEST")
    load_envvars(settings)
    assert settings.KEY == 123


def test_load_standard_settings_files(tmpdir):
    settings_file = tmpdir.join("settings.yaml")  # /etc/ansible-automation-platform/settings.yaml
    settings_file.write("key: 123")
    flags_file = tmpdir.join("flags.yaml")  # /etc/ansible-automation-platform/flags.yaml
    flags_file.write("FEATURE_NAME_ENABLED: true")
    secrets_file = tmpdir.join(".secrets.yaml")  # /etc/ansible-automation-platform/.secrets.yaml
    secrets_file.write("SECRET_KEY: 'b4t4t4'")

    settings = factory("", "TEST")
    settings.set("ANSIBLE_STANDARD_SETTINGS_FILES", [str(settings_file), str(flags_file), str(secrets_file)])
    load_standard_settings_files(settings)
    assert settings.key == 123
    assert settings.FEATURE_NAME_ENABLED is True
    assert settings.SECRET_KEY == "b4t4t4"


def test_validate():
    settings = factory("", "TEST", validators=[Validator("KEY", required=True, is_type_of=int, gt=10, lt=99)])

    # Ensure Raises ValidationError when key is not set
    try:
        validate(settings)
    except ValidationError as e:
        assert "KEY" in str(e)

    # Ensure Raises ValidationError when key is not an int
    settings.set("KEY", "potato")
    try:
        validate(settings)
    except ValidationError as e:
        assert "KEY" in str(e)

    # Ensure Raises ValidationError when key is less than 10
    settings.set("KEY", 9)
    try:
        validate(settings)
    except ValidationError as e:
        assert "KEY" in str(e)

    # Ensure Raises ValidationError when key is greater than 99
    settings.set("KEY", 100)
    try:
        validate(settings)
    except ValidationError as e:
        assert "KEY" in str(e)

    # Ensure key is set to 50 and no exception is raised
    settings.set("KEY", 50)
    validate(settings)
    assert settings.KEY == 50


def test_bypass_validation(monkeypatch):
    monkeypatch.setenv("BYPASS_DYNACONF_VALIDATION", "True")
    settings = factory("", "TEST", validators=[Validator("KEY", required=True, is_type_of=int, gt=10, lt=99)])

    # Ensure Raises ValidationError when key is not set is not raised
    validate(settings)

    # Ensure key is set to 9 and no exception is raised
    settings.set("KEY", 9)
    validate(settings)
    assert settings.KEY == 9

    # Ensure key is set to 100 and no exception is raised
    settings.set("KEY", 100)
    validate(settings)
    assert settings.KEY == 100

    # ENsure key is set to string and no exception is raised
    settings.set("KEY", "potato")
    validate(settings)
    assert settings.KEY == "potato"


def test_validates_before_export():
    """Assert export function validates before setting variables back to module object"""
    settings = factory("", "TEST", validators=[Validator("KEY", required=True, is_type_of=int, gt=10, lt=99)])
    settings.set("KEY", 123)

    class FakeModule: ...  # noqa: E701

    fake_module = FakeModule()
    try:
        export(fake_module, settings)
    except ValidationError as e:
        assert "KEY" in str(e)

    assert not hasattr(fake_module, "KEY")


def test_load_python_file_with_injected_scope(tmp_path):

    defaults = tmp_path / "defaults.py"
    defaults.write_text("COLORS = ['red']")

    extra_file = tmp_path / "test.py"
    extra_python = (
        "COLORS.append('green')",
        "from dynaconf import post_hook",
        "@post_hook",
        "def post_hook(settings):",
        "    return {'COLORS': '@merge blue'}",
    )
    extra_file.write_text("\n".join(extra_python))

    settings = factory("", "TEST", settings_files=[str(defaults)])
    load_python_file_with_injected_context(str(extra_file), settings=settings)
    assert settings.COLORS == ['red', 'green', 'blue']
    assert settings._loaded_files == [str(defaults), str(extra_file)]


def test_toggle_feature_flags():
    """Ensure that the toggle_feature_flags function works as expected."""

    settings = {
        "FLAGS": {
            "FEATURE_SOME_PLATFORM_FLAG_ENABLED": [
                {"condition": "boolean", "value": False, "required": True},
                {"condition": "before date", "value": "2022-06-01T12:00Z"},
            ]
        },
        "FEATURE_SOME_PLATFORM_FLAG_ENABLED": True,
    }
    assert toggle_feature_flags(settings) == {
        "FLAGS__FEATURE_SOME_PLATFORM_FLAG_ENABLED": [
            {"condition": "boolean", "value": True, "required": True},
            {"condition": "before date", "value": "2022-06-01T12:00Z"},
        ]
    }
