from typing import Optional

from django.contrib.auth import get_user_model

from ansible_base.authentication.models import Authenticator

User = get_user_model()


def is_external_account(user: User) -> Optional[Authenticator]:
    """
    Determines whether the user is associated with any external
    login source. If they are, return the source. Otherwise, None.

    :param user: The user to test
    :return: If the user is associated with any external login source, return it (the first, if multiple)
             Otherwise, return None
    """
    authenticator_users = user.authenticator_users.all()
    local = 'ansible_base.authentication.authenticator_plugins.local'
    for auth_user in authenticator_users:
        if auth_user.provider.type != local:
            return auth_user.provider

    return None
