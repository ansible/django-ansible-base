from ansible_base.authentication.models import AuthenticatorUser


def is_external_account(user) -> bool:
    # True if the user is associated with any external login source
    # False if the user is associated only with the local
    # None if there is no user

    if not user:
        return None

    authenticator_users = AuthenticatorUser.objects.filter(user_id=user.id)
    for auth_user in authenticator_users:
        provider = auth_user.provider
        if provider.type != 'ansible_base.authenticator_plugins.local':
            return True

    # This user was not associated with any providers that were not the local provider
    return False
