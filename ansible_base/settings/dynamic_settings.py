if ANSIBLE_BASE_FEATURES.get('AUTHENTICATION', False):  # noqa: F821
    try:
        AUTHENTICATION_BACKENDS  # noqa: F821
    except NameError:
        AUTHENTICATION_BACKENDS = ["ansible_base.authentication.backend.AnsibleBaseAuth"]

    middleware_class = 'ansible_base.utils.middleware.AuthenticatorBackendMiddleware'
    try:
        MIDDLEWARE  # noqa: F821
        if middleware_class not in MIDDLEWARE:  # noqa: F821
            try:
                index = MIDDLEWARE.index('django.contrib.auth.middleware.AuthenticationMiddleware')  # noqa: F821
                MIDDLEWARE.insert(index, middleware_class)  # noqa: F821
            except ValueError:
                MIDDLEWARE.append(middleware_class)  # noqa: F821
    except NameError:
        MIDDLEWARE = [middleware_class]

    drf_authentication_class = 'ansible_base.authentication.session.SessionAuthentication'
    if 'DEFAULT_AUTHENTICATION_CLASSES' not in REST_FRAMEWORK:  # noqa: F821
        REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'] = []  # noqa: F821
    if drf_authentication_class not in REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES']:  # noqa: F821
        REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'].insert(0, drf_authentication_class)  # noqa: F821

    try:
        ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIXES  # noqa: F821
    except NameError:
        ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIXES = ["ansible_base.authenticator_plugins"]
    SOCIAL_AUTH_PIPELINE = (
        'social_core.pipeline.social_auth.social_details',
        'social_core.pipeline.social_auth.social_uid',
        'social_core.pipeline.social_auth.auth_allowed',
        'social_core.pipeline.social_auth.social_user',
        'social_core.pipeline.user.get_username',
        'social_core.pipeline.user.create_user',
        'social_core.pipeline.social_auth.associate_user',
        'social_core.pipeline.social_auth.load_extra_data',
        'social_core.pipeline.user.user_details',
        'ansible_base.authentication.social_auth.create_user_claims_pipeline',
    )
    SOCIAL_AUTH_STORAGE = "ansible_base.authentication.social_auth.AuthenticatorStorage"
    SOCIAL_AUTH_STRATEGY = "ansible_base.authentication.social_auth.AuthenticatorStrategy"
    SOCIAL_AUTH_LOGIN_REDIRECT_URL = "/"


if ANSIBLE_BASE_FEATURES.get('SWAGGER', False):  # noqa: F821
    if 'drf_spectacular' not in INSTALLED_APPS:  # noqa: F821
        INSTALLED_APPS.append('drf_spectacular')  # noqa: F821
