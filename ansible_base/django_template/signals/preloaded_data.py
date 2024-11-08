import logging

from django.apps import apps as global_apps

from ansible_base.lib.utils.auth import get_organization_model
from ansible_base.lib.utils.models import get_system_user
from ansible_base.rbac.permission_registry import permission_registry

logger = logging.getLogger('ansible_base.django_template.signals.preloaded_data')


def create_preload_data(**kwargs) -> None:
    """
    Run functions in a given order to create pre-loaded data
    All functions in this code should take no arguments and be idempotent
    If they fail, an exception (of any type) should be raised
    If an exception is raised the message "Failed to <function name replace _ with ' '>" is outputted in the logs
    """

    function_order = [
        create_default_organization,
        create_managed_roles,
        # set_system_user_password,
        # set_system_user_managed_flag,
    ]

    # Verbosity comes from the signal see https://docs.djangoproject.com/en/5.0/ref/signals/#post-migrate
    verbosity = kwargs.get('verbosity', 1)

    # Plan comes from the signal as well.
    # If this got called outside of a signal or presumably from a flush it may not exist
    if 'plan' not in kwargs:
        # If we are are being called via a flush instead of a migrate then we can just return
        return

    for migration, rolled_back in kwargs['plan']:
        if rolled_back:
            if verbosity > 0:
                logger.debug(f"We are rolling back migration {migration}, no need to create objects")
            return

    if verbosity > 0:
        logger.info("Building preloaded data")

    for function in function_order:
        name = function.__name__
        try:
            if verbosity > 1:
                logger.info(f"Running {name}")
            created = function()
            if verbosity > 0 and created:
                action = 'Created'
                if name.startswith('set'):
                    action = 'Set'
                logger.debug(f"{action} {' '.join(name.split('_')[1:])}")
        except Exception as e:
            # raise e
            if verbosity in [0, 1]:
                logger.error(f"Failed to {name.replace('_', ' ')} {e}")
            elif verbosity > 1:
                logger.exception(f"Failed to {name.replace('_', ' ')}")


def create_default_organization() -> bool:
    _org, created = get_organization_model().objects.get_or_create(
        name='Default', defaults={'managed': True, 'description': 'The default organization for Ansible Automation Platform'}
    )
    return created


def create_managed_roles() -> None:
    permission_registry.create_managed_roles(global_apps)


def set_system_user_password() -> bool:
    # When the system user is created by a migration it can't call set_usable_password because is of class <__fake__.User>
    system_user = get_system_user()
    if system_user.has_usable_password:
        system_user.set_unusable_password()
        system_user.save()
        return True
    else:
        return False


def set_system_user_managed_flag() -> None:
    system_user = get_system_user()
    if system_user.managed:
        return False
    system_user.managed = True
    system_user.save()
    return True
