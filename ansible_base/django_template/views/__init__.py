from ansible_base.django_template.views.api.v1 import V1RootView  # noqa: F401
from ansible_base.django_template.views.api.v1.local_login import LoggedLoginView, LoggedLogoutView  # noqa: F401
from ansible_base.django_template.views.api.v1.me import MeViewSet  # noqa: F401
from ansible_base.django_template.views.api.v1.organization import OrganizationViewSet  # noqa: F401
from ansible_base.django_template.views.api.v1.ping import PingView  # noqa: F401
from ansible_base.django_template.views.api.v1.related_views import UserOrganizationViewSet, UserTeamViewSet  # noqa: F401
from ansible_base.django_template.views.api.v1.session import SessionView  # noqa: F401
from ansible_base.django_template.views.api.v1.team import TeamViewSet  # noqa: F401
from ansible_base.django_template.views.api.v1.user import UserViewSet  # noqa: F401

from django.core.exceptions import FieldError
from django.db import IntegrityError
from rest_framework.exceptions import ParseError
from rest_framework.views import exception_handler

def api_exception_handler(exc, context):
    """
    Override default API exception handler to catch IntegrityError exceptions.
    """
    if isinstance(exc, IntegrityError):
        exc = ParseError(exc.args[0])
    if isinstance(exc, FieldError):
        exc = ParseError(exc.args[0])
    return exception_handler(exc, context)
