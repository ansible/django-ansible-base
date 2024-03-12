import importlib
import logging

from django.conf import settings
from django.utils.translation import gettext_lazy as _
from rest_framework.filters import SearchFilter

from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from ansible_base.rest_filters.rest_framework.field_lookup_backend import FieldLookupBackend
from ansible_base.rest_filters.rest_framework.order_backend import OrderByBackend
from ansible_base.rest_filters.rest_framework.type_filter_backend import TypeFilterBackend

logger = logging.getLogger('ansible_base.lib.utils.views.django_app_api')


# Determine and load the parent view
# If anything fails in here its a pretty low level exception so we don't catch anything and just let it raise
parent_view = getattr(settings, 'ANSIBLE_BASE_CUSTOM_VIEW_PARENT', None)
parent_view_class = AnsibleBaseView
if parent_view:
    try:
        module_name, junk, class_name = parent_view.rpartition('.')
        logger.debug(_("Trying to import parent view {class_name} from package {module_name}".format(class_name=class_name, module_name=module_name)))
        if not module_name or not class_name:
            logger.error(_("ANSIBLE_BASE_CUSTOM_VIEW_PARENT must be in the format package.subpackage.view, defaulting to AnsibleBaseView"))
        else:
            module = importlib.import_module(module_name, package=class_name)
            parent_view_class = getattr(module, class_name)
    except ModuleNotFoundError:
        logger.error(_("Failed to find parent view class {parent_view}, defaulting to AnsibleBaseView".format(parent_view=parent_view)))
    except ImportError:
        logger.exception(_("Failed to import {parent_view}, defaulting to AnsibleBaseView".format(parent_view=parent_view)))


class AnsibleBaseDjangoAppApiView(parent_view_class):
    # In case an app is using features like authentication, resources, or RBAC
    # but not using rest_filters app, we need to specify the same filter backends
    filter_backends = (TypeFilterBackend, FieldLookupBackend, SearchFilter, OrderByBackend)
