import logging
import time
from collections import namedtuple
from typing import Optional

import requests
import urllib3
from django.apps import apps

from ansible_base.resource_registry.resource_server import get_resource_server_config, get_service_token

ResourceRequestBody = namedtuple(
    "ResourceRequestBody",
    ["ansible_id", "service_id", "is_partially_migrated", "resource_type", "resource_data"],
    defaults=(None, None, None, None, None),
)


urllib3.disable_warnings()

logger = logging.getLogger('ansible_base.resources_api.rest_client')


def get_resource_server_client(service_path, **kwargs) -> "ResourceAPIClient":
    config = get_resource_server_config()

    return ResourceAPIClient(
        service_url=config["URL"],
        service_path=service_path,
        verify_https=config["VALIDATE_HTTPS"],
        **kwargs,
    )


class ResourceAPIClient:
    """
    Client for Ansible services to interact with the service-index/ api
    """

    header_name = "X-ANSIBLE-SERVICE-AUTH"
    _jwt_timeout = None
    _jwt = None

    def __init__(
        self,
        service_url: str,
        service_path: str,
        verify_https=True,
        raise_if_bad_request: bool = False,
        jwt_user_id=None,
        jwt_expiration=60,
    ):
        """
        service_url (str): fully qualified hostname for the service that the client
            is connecting to (http://www.example.com:123).
        service_path (str): path on the service where the service-index/ api is found
            (/api/v1/service-index/).
        verify_https (bool): check the server's SSL certificates
        raise_if_bad_request (bool): raise an exception if the API call returns a non
            successful status code.
        jwt_user_id (UUID): ansible ID of the user to make the request as.
        jwt_expiration (int): number of seconds that the JWT token is valid.
        """
        if jwt_user_id is not None:
            jwt_user_id = str(jwt_user_id)

        self.base_url = f"{service_url}/{service_path.strip('/')}/"
        self.verify_https = verify_https
        self.raise_if_bad_request = raise_if_bad_request
        self.jwt_user_id = jwt_user_id
        self.jwt_expiration = jwt_expiration
        self._jwt = None
        self._jwt_timeout = None

    def refresh_jwt(self):
        # Add a buffer to the token timeout to account for slower requests.
        self._jwt_timeout = time.time() + (self.jwt_expiration - 2)
        self._jwt = get_service_token(self.jwt_user_id, expiration=self.jwt_expiration)

    @property
    def jwt(self):
        if self._jwt is None or self._jwt_timeout is None or time.time() >= self._jwt_timeout:
            self.refresh_jwt()

        return self._jwt

    @property
    def requests_auth_kwargs(self):
        return {"headers": {self.header_name: self.jwt}}

    def _make_request(
        self,
        method: str,
        path: str,
        data: Optional[dict] = None,
        params: Optional[dict] = None,
        stream: bool = False,
    ) -> requests.Response:
        url = self.base_url + path.lstrip("/")
        logger.info(f"Making {method} request to {url}.")

        kwargs = {**self.requests_auth_kwargs, "method": method, "url": url, "verify": self.verify_https}

        if data:
            kwargs["json"] = data
        if params:
            kwargs["params"] = params
        if stream:
            kwargs["stream"] = stream

        resp = requests.request(**kwargs)
        logger.debug(f"Response status code from {url}: {resp.status_code}")

        if self.raise_if_bad_request:
            try:
                resp.raise_for_status()
            except requests.exceptions.HTTPError as e:
                content = resp.text

                # Re-raise with more context
                raise requests.exceptions.HTTPError(f"{e}\nResponse content: {content}", response=resp) from None
        return resp

    def _get_request_dict(self, data: ResourceRequestBody):
        raw_dict = data._asdict()
        req_dict = {}
        for k in raw_dict:
            if raw_dict[k] is not None:
                # Convert UUIDs to strings
                if k in ("ansible_id", "service_id"):
                    req_dict[k] = str(raw_dict[k])
                else:
                    req_dict[k] = raw_dict[k]
        return req_dict

    def get_service_metadata(self):
        return self._make_request("get", "metadata/")

    def create_resource(self, data: ResourceRequestBody):
        return self._make_request("post", "resources/", self._get_request_dict(data))

    def get_resource(self, ansible_id):
        return self._make_request("get", f"resources/{ansible_id}/")

    def get_additional_resource_data(self, ansible_id):
        return self._make_request("get", f"resources/{ansible_id}/additional_data/")

    def update_resource(self, ansible_id, data: ResourceRequestBody, partial=False):
        action = "patch" if partial else "put"
        return self._make_request(action, f"resources/{ansible_id}/", self._get_request_dict(data))

    def delete_resource(self, ansible_id):
        return self._make_request("delete", f"resources/{ansible_id}/")

    def list_resources(self, filters: Optional[dict] = None):
        return self._make_request("get", "resources/", params=filters)

    def get_resource_type(self, name):
        return self._make_request("get", f"resource-types/{name}/")

    def list_resource_types(self, filters: Optional[dict] = None):
        return self._make_request("get", "resource-types/", params=filters)

    def get_resource_type_manifest(self, name, filters: Optional[dict] = None):
        return self._make_request("get", f"resource-types/{name}/manifest/", params=filters, stream=True)

    # RBAC related methods
    def list_role_types(self, filters: Optional[dict] = None):
        return self._make_request("get", "role-types/", params=filters)

    def list_role_permissions(self, filters: Optional[dict] = None):
        return self._make_request("get", "role-permissions/", params=filters)

    def list_user_assignments(self, user_ansible_id: Optional[str] = None, filters: Optional[dict] = None):
        """List user role assignments."""
        params = (filters or {}).copy()
        if user_ansible_id is not None:
            params['user_ansible_id'] = user_ansible_id
        return self._make_request("get", "role-user-assignments/", params=params)

    def list_team_assignments(self, team_ansible_id: Optional[str] = None, filters: Optional[dict] = None):
        """List team role assignments."""
        params = (filters or {}).copy()
        if team_ansible_id is not None:
            params['team_ansible_id'] = team_ansible_id
        return self._make_request("get", "role-team-assignments/", params=params)

    def sync_assignment(self, assignment):
        from ansible_base.rbac.service_api.serializers import ServiceRoleTeamAssignmentSerializer, ServiceRoleUserAssignmentSerializer

        if assignment._meta.model_name == 'roleuserassignment':
            serializer = ServiceRoleUserAssignmentSerializer(assignment)
        else:
            serializer = ServiceRoleTeamAssignmentSerializer(assignment)

        return self._sync_assignment(serializer.data)

    def sync_unassignment(self, role_definition, actor, content_object):
        data = {'role_definition': role_definition.name}
        data[f'{actor._meta.model_name}_ansible_id'] = str(actor.resource.ansible_id)

        if content_object is None:
            data['object_id'] = None
        else:
            ct_cls = apps.get_model('dab_rbac', 'DABContentType')
            ct = ct_cls.objects.get_for_model(content_object)
            if ct.service == 'shared':
                data['object_ansible_id'] = str(content_object.resource.ansible_id)
            else:
                # Convert pk to string to handle UUID objects for JSON serialization
                data["object_id"] = str(content_object.pk)

        return self._sync_assignment(data, giving=False)

    def sync_object_deletion(self, content_object):
        """Sync object deletion to Gateway for cleanup of all related role assignments"""
        from ansible_base.rbac.models import DABContentType

        # Get the content type information
        content_type = DABContentType.objects.get_for_model(content_object)

        data = {
            'resource_type': f'{content_type.app_label}.{content_type.model}',
            'resource_pk': str(content_object.pk),  # Convert pk to string for JSON serialization
        }

        # Make single API call to the new object-delete endpoint
        response = self._make_request("post", "object-delete/", data=data)

        if response.status_code == 200:
            return response.json()
        else:
            return {'error': f'Failed with status {response.status_code}', 'status_code': response.status_code}

    def _sync_assignment(self, data, giving=True):
        if giving:
            sub_url = 'assign'
        else:
            sub_url = 'unassign'

        actor_type = 'user'
        if data.get('team_ansible_id'):
            actor_type = 'team'

        url = f'role-{actor_type}-assignments/{sub_url}/'

        return self._make_request("post", url, data=data)
