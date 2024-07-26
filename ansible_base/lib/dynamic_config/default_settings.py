from types import SimpleNamespace


authentication = SimpleNamespace(
    ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIXES = ["ansible_base.authentication.authenticator_plugins"],

    SOCIAL_AUTH_PIPELINE = (
        'social_core.pipeline.social_auth.social_details',
        'social_core.pipeline.social_auth.social_uid',
        'social_core.pipeline.social_auth.auth_allowed',
        'social_core.pipeline.social_auth.social_user',
        'ansible_base.authentication.utils.authentication.determine_username_from_uid_social',
        'social_core.pipeline.user.create_user',
        'social_core.pipeline.social_auth.associate_user',
        'social_core.pipeline.social_auth.load_extra_data',
        'social_core.pipeline.user.user_details',
        'ansible_base.authentication.social_auth.create_user_claims_pipeline',
    ),
    SOCIAL_AUTH_STORAGE = "ansible_base.authentication.social_auth.AuthenticatorStorage",
    SOCIAL_AUTH_STRATEGY = "ansible_base.authentication.social_auth.AuthenticatorStrategy",
    SOCIAL_AUTH_LOGIN_REDIRECT_URL = "/",

    ANSIBLE_BASE_SOCIAL_AUDITOR_FLAG = "is_system_auditor",

    # URL to send users when social auth login fails
    LOGIN_ERROR_URL = "/?auth_failed"
)

rbac = SimpleNamespace(
    # The settings-based specification of managed roles from DAB RBAC vendored ones
    ANSIBLE_BASE_MANAGED_ROLE_REGISTRY = {},

    # Permissions a user will get when creating a new item
    ANSIBLE_BASE_CREATOR_DEFAULTS = ['add', 'change', 'delete', 'view'],
    # Permissions API will check for related items, think PATCH/PUT
    # This is a precedence order, so first action related model has will be used
    ANSIBLE_BASE_CHECK_RELATED_PERMISSIONS = ['use', 'change', 'view'],
    # If a role does not already exist that can give those object permissions
    # then the system must create one, this is used for naming the auto-created role
    ANSIBLE_BASE_ROLE_CREATOR_NAME = '{obj._meta.model_name}-creator-permission',

    # Require change permission to get delete permission
    ANSIBLE_BASE_DELETE_REQUIRE_CHANGE = True,
    # Specific feature enablement bits
    # For assignments
    ANSIBLE_BASE_ALLOW_TEAM_PARENTS = True,
    ANSIBLE_BASE_ALLOW_TEAM_ORG_PERMS = True,
    ANSIBLE_BASE_ALLOW_TEAM_ORG_MEMBER = False,
    ANSIBLE_BASE_ALLOW_TEAM_ORG_ADMIN = True,
    # For role definitions
    ANSIBLE_BASE_ALLOW_CUSTOM_ROLES = True,
    ANSIBLE_BASE_ALLOW_CUSTOM_TEAM_ROLES = False,
    # Allows managing singleton permissions
    ANSIBLE_BASE_ALLOW_SINGLETON_USER_ROLES = False,
    ANSIBLE_BASE_ALLOW_SINGLETON_TEAM_ROLES = False,
    ANSIBLE_BASE_ALLOW_SINGLETON_ROLES_API = True,

    # Pass ignore_conflicts=True for bulk_create calls for role evaluations
    # this should be fine to resolve cross-process conflicts as long as
    # directionality is the same - adding or removing permissions
    # A value of False would result in more errors but be more conservative
    ANSIBLE_BASE_EVALUATIONS_IGNORE_CONFLICTS = True,

    # User flags that can grant permission before consulting roles
    ANSIBLE_BASE_BYPASS_SUPERUSER_FLAGS = ['is_superuser'],
    ANSIBLE_BASE_BYPASS_ACTION_FLAGS = {},

    # Save RoleEvaluation entries for child permissions on parent models
    # ex: organization roles giving view_inventory permission will save
    # entries mapping that permission to the assignment's organization
    ANSIBLE_BASE_CACHE_PARENT_PERMISSIONS = False,

    # API clients can assign users and teams roles for shared resources
    ALLOW_LOCAL_RESOURCE_MANAGEMENT = True,

    MANAGE_ORGANIZATION_AUTH = True,
    ORG_ADMINS_CAN_SEE_ALL_USERS = True,
)


oauth2_provider = SimpleNamespace(
    # These have to be defined for the migration to function
    OAUTH2_PROVIDER_APPLICATION_MODEL = 'dab_oauth2_provider.OAuth2Application',
    OAUTH2_PROVIDER_ACCESS_TOKEN_MODEL = 'dab_oauth2_provider.OAuth2AccessToken',
    OAUTH2_PROVIDER_REFRESH_TOKEN_MODEL = "dab_oauth2_provider.OAuth2RefreshToken",
    OAUTH2_PROVIDER_ID_TOKEN_MODEL = "dab_oauth2_provider.OAuth2IDToken",

    ALLOW_OAUTH2_FOR_EXTERNAL_USERS = False
)
