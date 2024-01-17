from os import path
from textwrap import dedent

from ansible_base import settings as ab_settings


def get_updated_settings(additional_config):
    file_name = path.join(path.dirname(ab_settings.__file__), 'dynamic_settings.py')
    code_to_compile = ''
    with open(file_name, 'r') as to_compile:
        code_to_compile = to_compile.read()

    code = f'{additional_config}\n{code_to_compile}'

    updated_settings = {}
    compiled_code = compile(code, file_name, 'exec')  # noqa: WPS421
    exec(compiled_code, updated_settings)  # noqa: S102, WPS421
    return updated_settings


def test_swagger_disabled():
    additional_settings = dedent(
        '''
        ANSIBLE_BASE_FEATURES = {
            'SWAGGER': False,
        }
        '''
    )
    updated_settings = get_updated_settings(additional_settings)
    assert 'drf_spectacular' not in updated_settings['INSTALLED_APPS']


def test_swagger_enabled():
    additional_settings = dedent(
        '''
        ANSIBLE_BASE_FEATURES = {'SWAGGER': True}
    '''
    )
    updated_settings = get_updated_settings(additional_settings)

    assert 'drf_spectacular' in updated_settings['INSTALLED_APPS']


def test_authentication_with_backends():
    additional_config = dedent(
        '''
        AUTHENTICATION_BACKENDS = ['something']
        INSTALLED_APPS = ['ansible_base.authentication']
    '''
    )
    updated_settings = get_updated_settings(additional_config)

    assert 'ansible_base.authentication.backend.AnsibleBaseAuth' not in updated_settings['AUTHENTICATION_BACKENDS']
    # This also tests some other "happy paths"
    assert 'ansible_base.authentication.middleware.AuthenticatorBackendMiddleware' in updated_settings['MIDDLEWARE']
    assert 'ansible_base.authentication.session.SessionAuthentication' in updated_settings['REST_FRAMEWORK']['DEFAULT_AUTHENTICATION_CLASSES']
    assert 'ansible_base.authentication.authenticator_plugins' in updated_settings['ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIXES']
    assert 'SOCIAL_AUTH_LOGIN_REDIRECT_URL' in updated_settings


def test_authentication_no_backends():
    additional_config = dedent(
        '''
        INSTALLED_APPS = ['ansible_base.authentication']
    '''
    )
    updated_settings = get_updated_settings(additional_config)
    assert 'ansible_base.authentication.backend.AnsibleBaseAuth' in updated_settings['AUTHENTICATION_BACKENDS']


def test_append_middleware():
    additional_config = dedent(
        '''
        INSTALLED_APPS = ['ansible_base.authentication']
        REST_FRAMEWORK = {}
        MIDDLEWARE=['something']
    '''
    )
    updated_settings = get_updated_settings(additional_config)
    assert 'ansible_base.authentication.middleware.AuthenticatorBackendMiddleware' == updated_settings['MIDDLEWARE'][-1]


def test_insert_middleware():
    additional_config = dedent(
        '''
        INSTALLED_APPS = ['ansible_base.authentication']
        MIDDLEWARE=['something', 'django.contrib.auth.middleware.AuthenticationMiddleware', 'else']
    '''
    )
    updated_settings = get_updated_settings(additional_config)
    assert 'ansible_base.authentication.middleware.AuthenticatorBackendMiddleware' == updated_settings['MIDDLEWARE'][1]


def test_dont_update_class_prefixes():
    additional_config = dedent(
        '''
        INSTALLED_APPS = ['ansible_base.authentication']
        ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIXES = ['other.things']
    '''
    )
    updated_settings = get_updated_settings(additional_config)
    assert 'ansible_base.authentication.authenticator_plugins' not in updated_settings['ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIXES']


def test_filtering():
    additional_config = dedent(
        '''
        ANSIBLE_BASE_FEATURES = {'FILTERING': True}
        REST_FRAMEWORK = {}
    '''
    )
    updated_settings = get_updated_settings(additional_config)
    assert 'ansible_base.filters.rest_framework.type_filter_backend.TypeFilterBackend' in updated_settings['REST_FRAMEWORK']['DEFAULT_FILTER_BACKENDS']
