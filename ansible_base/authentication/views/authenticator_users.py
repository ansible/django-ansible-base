import importlib
import logging
from types import ModuleType

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import Http404

from ansible_base.authentication.models import Authenticator
from ansible_base.lib.utils.views.permissions import IsSuperuserOrAuditor

logger = logging.getLogger('ansible_base.authentication.views.authenticator_users')


def get_authenticator_user_view():
    try:
        user_viewset_name = settings.ANSIBLE_BASE_USER_VIEWSET
        module_name, _junk, class_name = user_viewset_name.rpartition('.')
        module = importlib.import_module(module_name, package=class_name)
        user_viewset_view = getattr(module, class_name)
        if isinstance(user_viewset_view, ModuleType):
            raise ModuleNotFoundError()

        class AuthenticatorPluginRelatedUsersView(user_viewset_view):
            permission_classes = [IsSuperuserOrAuditor]

            def get_queryset(self, **kwargs):
                # during unit testing we get the pk from kwargs
                authenticator_id = kwargs.get('pk', None)
                if hasattr(self, 'kwargs'):
                    # But at runtime self has kwargs attached and no kwargs associated
                    authenticator_id = self.kwargs.get('pk', None)
                # if we didn't get an ID for some reason we will just return None
                if authenticator_id is None or not Authenticator.objects.filter(pk=authenticator_id).exists():
                    raise Http404()
                    # return get_user_model().objects.none()
                authenticator_users = get_user_model().objects.filter(authenticator_users__provider__id=authenticator_id)
                return authenticator_users

        return AuthenticatorPluginRelatedUsersView
    except ModuleNotFoundError:
        logger.error("ANSIBLE_BASE_USER_VIEWSET was not an APIView")
    except AttributeError:
        logger.debug("ANSIBLE_BASE_USER_VIEWSET was not specified")
    except Http404:
        logger.error("Authenticator not available")

    return None
