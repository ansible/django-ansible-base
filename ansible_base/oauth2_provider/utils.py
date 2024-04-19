from django.contrib.auth import get_user_model

User = get_user_model()


def is_external_account(user: User) -> bool:
    """
    Predicate which tests whether the user is associated with any external
    login source.

    :param user: The user to test
    :return: True if the user is associated with any external login source
             False if the user is associated only with the local
    """
    authenticator_users = user.authenticator_users.all()
    local = 'ansible_base.authentication.authenticator_plugins.local'
    return any(auth_user.provider.type != local for auth_user in authenticator_users)
