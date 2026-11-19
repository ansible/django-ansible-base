from typing import Iterable, Optional, Type, Union

from django.apps import AppConfig
from django.conf import settings
from django.core.checks import CheckMessage, Debug, Error, Warning
from rest_framework.permissions import AllowAny, OperandHolder, OperationHolderMixin, SingleOperandHolder
from rest_framework.views import APIView

from ansible_base.lib.permissions import TokenScopePermission
from ansible_base.lib.utils.views.urls import get_api_view_functions


class TokenScopePermissionCheck:
    """
    Class containing logic for checking view classes for the
    TokenScopePermission permission class, and aggregating
    CheckMessage's for django system checks.

    :param ignore_list: List of python import path strings for view classes exempt from the check logic.
    :type ignore_list: list
    """

    def __init__(self, ignore_list: Iterable[str], generate_check_messages=True):
        self.messages: list[CheckMessage] = []
        self.current_view: Optional[Type[APIView]] = None
        self.ignore_list = ignore_list
        self.generate_check_messages = generate_check_messages

    def check_message(self, message: CheckMessage):
        if self.generate_check_messages:
            self.messages.append(message)

    # These are all warning or error conditions, this function is mostly saying to not invert TokenScopePermission.
    # Returns False.
    def process_single_operand_holder(self, operand_holder: SingleOperandHolder) -> bool:
        # The only unary operand for permission classes provided by rest_framework is ~ (not)
        if self.parse_permission_class(operand_holder.op1_class):
            self.check_message(
                Warning(
                    "~ (not) operand used on TokenScopePermission, probably a bad idea.",
                    id="ansible_base.oauth2_provider.W001",
                    obj=self.current_view,
                )
            )

        return False

    def process_operand_holder(self, operand_holder: OperandHolder) -> bool:
        return self.parse_permission_class(operand_holder.op1_class) or self.parse_permission_class(operand_holder.op2_class)

    # Check if permission class is present in nested operands
    # Sort of recursive? Reasonably this should not be an issue, so long as we don't recurse on an unknown OperationHolderMixin type
    def parse_permission_class(self, cls: Union[Type[OperationHolderMixin], OperationHolderMixin]) -> bool:
        # First, most likely case, we're dealing with a BasePermission subclass.
        if isinstance(cls, type) and issubclass(cls, TokenScopePermission):
            return True
        elif isinstance(cls, SingleOperandHolder):
            # Warning or Error case: Will not accept a scope permission nested in NOT.
            return self.process_single_operand_holder(cls)
        elif isinstance(cls, OperandHolder):
            return self.process_operand_holder(cls)
        return False

    def check_view(self, view_class: Type[APIView]) -> bool:
        """
        Primary function of the TokenScopePermissionCheck.

        Checks if TokenScopePermission is present on the supplied view's
        permission_classes; ignores classes that are not APIViews, or that are
        in the ignore_list.

        Appends CheckMessages to self.messages as a side effect.

        :param view_class: django View class or rest_framework ApiView class

        :return: True if view_class uses the TokenScopePermission permission
            class, or has some mitigating circumstance that prohibits it, such as
            view_class not using permission classes, or its import path being in
            self.ignore_list; returns False otherwise.
        """
        if f"{view_class.__module__}.{view_class.__name__}" in self.ignore_list:
            self.check_message(
                Debug(
                    "View class in the ignore list. Ignoring.",
                    obj=view_class,
                    id="ansible_base.oauth2_provider.D03",
                )
            )
            return True

        self.current_view = view_class

        for permission_class in getattr(self.current_view, "permission_classes", []):
            if self.parse_permission_class(permission_class):
                self.check_message(
                    Debug(
                        "Found TokenScopePermission permission_class",
                        obj=self.current_view,
                        id="ansible_base.oauth2_provider.D02",
                    )
                )
                return True

        if not self.current_view.permission_classes or AllowAny in self.current_view.permission_classes:
            self.check_message(
                Debug(
                    "View object is fully permissive, TokenScopePermission is not required",
                    obj=self.current_view,
                    id="ansible_base.oauth2_provider.D04",
                )
            )
            return True

        # if we went though the whole loop without finding a valid permission_class, raise an error
        self.check_message(
            Error(
                "View class has no valid usage of TokenScopePermission",
                obj=self.current_view,
                id="ansible_base.oauth2_provider.E002",
            )
        )
        return False


def view_in_app_configs(view_class: type, app_configs: Optional[list[AppConfig]]) -> bool:
    if app_configs:
        for app_config in app_configs:
            if view_class.__module__.startswith(app_config.name):
                return True
        return False
    return True


def oauth2_permission_scope_check(app_configs: Optional[list[AppConfig]], **kwargs) -> list[CheckMessage]:
    """
    Check for TokenScopePermission permission class on all enabled views.

    Ignore views in the ANSIBLE_BASE_OAUTH2_PROVIDER_PERMISSIONS_CHECK_IGNORED_VIEWS setting
    """
    ignore_list = set(
        getattr(settings, "ANSIBLE_BASE_OAUTH2_PROVIDER_PERMISSIONS_CHECK_DEFAULT_IGNORED_VIEWS", [])
        + getattr(settings, "ANSIBLE_BASE_OAUTH2_PROVIDER_PERMISSIONS_CHECK_IGNORED_VIEWS", [])
    )

    check = TokenScopePermissionCheck(ignore_list)

    view_functions = get_api_view_functions()
    for view in view_functions:
        # Only run checks on included apps (or all if app_configs is None)
        if view_in_app_configs(view, app_configs):
            check.check_view(view)

    return check.messages
