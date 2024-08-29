import logging
import os

from crum import get_current_user
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from ansible_base.resource_registry.models import Resource
from ansible_base.resource_registry.rest_client import ResourceRequestBody, get_resource_server_client

logger = logging.getLogger('ansible_base.resource_registry.utils.sync_to_resource_server')


def sync_to_resource_server(instance, action, ansible_id=None):
    """
    Use the resource server API to sync the resource across.

    When action is "delete", the ansible_id is required, because by the time we
    get here, we've already deleted the object and its resource. So we can't
    pull the ansible_id from the resource object. It's on the caller to pull
    the ansible_id from the object before deleting it.

    For all other actions, ansible_id is ignored and retrieved from the resource
    object. (For create, the resource is expected to exist before calling this
    function.)
    """

    sync_disabled = os.environ.get('ANSIBLE_REVERSE_RESOURCE_SYNC', 'true').lower() == 'false'
    if sync_disabled:
        logger.info("Skipping sync of resource {instance} because $ANSIBLE_REVERSE_RESOURCE_SYNC is 'false'")
        return

    # This gets set in in signals.handlers.decide_to_sync_update() sometimes.
    skip_sync = getattr(instance, '_skip_reverse_resource_sync', False)
    if skip_sync:
        # Avoid an infinite loop by not syncing resources that came from the resource server.
        # Or avoid syncing unnecessarily, when a synced field hasn't changed.
        logger.info(f"Skipping sync of resource {instance}")
        return

    try:
        if action != "delete" and ansible_id is not None:
            raise Exception("ansible_id should not be provided for create/update actions")
        elif action == "delete" and ansible_id is None:
            raise Exception("ansible_id should be provided for delete actions")
        elif not getattr(instance, 'resource', None) or not instance.resource.ansible_id:
            # We can't sync if we don't have a resource and an ansible_id.
            logger.error(f"Resource {instance} does not have a resource or ansible_id")
            return
    except Resource.DoesNotExist:
        # The getattr() will raise a Resource.DoesNotExist if the resource doesn't exist.
        logger.error(f"Resource {instance} does not have a resource")
        return

    user_ansible_id = None
    user = get_current_user()
    if user:
        # If we have a user, try to get their ansible_id and sync as them.
        # If they don't have one some how, or if we don't have a user, sync with None and
        # let the resource server decide what to do.
        try:
            user_ansible_id = user.resource.ansible_id
        except AttributeError:
            logger.error(f"User {user} does not have a resource")
            pass
    else:
        logger.error("No user found, syncing to resource server with jwt_user_id=None")

    client = get_resource_server_client(
        settings.RESOURCE_SERVICE_PATH,
        jwt_user_id=user_ansible_id,
        raise_if_bad_request=True,
    )

    if action != "delete":
        ansible_id = instance.resource.ansible_id

    resource_type = instance.resource.content_type.resource_type
    data = resource_type.serializer_class(instance).data
    body = ResourceRequestBody(
        resource_type=resource_type.name,
        ansible_id=ansible_id,
        resource_data=data,
    )

    try:
        if action == "create":
            response = client.create_resource(body)
            json = response.json()
            if isinstance(json, dict):  # Mainly for tests... to avoid getting here with mock
                instance.resource.service_id = json['service_id']
                instance.resource.save()
        elif action == "update":
            client.update_resource(ansible_id, body)
        elif action == "delete":
            client.delete_resource(ansible_id)
    except Exception as e:
        logger.exception(f"Failed to sync {action} of resource {instance} ({ansible_id}) to resource server: {e}")
        raise ValidationError(_("Failed to sync resource to resource server")) from e
