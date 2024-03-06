import logging
from collections import namedtuple

import requests
import urllib3

ResourceRequestBody = namedtuple("ResourceRequestBody", ["ansible_id", "service_id", "resource_type", "resource_data"], defaults=(None, None, None, None))


urllib3.disable_warnings()

logger = logging.getLogger('ansible_base.resources_api.rest_client')


class ResourceAPIClient:
    """
    Client for Ansible services to interact with the service-index/ api
    """

    def __init__(self, service_url: str, service_path: str, requests_auth_kwargs: dict, verify_https=True):
        """
        service_url: fully qualified hostname for the service that the client
            is connecting to (http://www.example.com:123).
        service_path: path on the service where the service-index/ api is found
            (/api/v1/service-index/).
        requests_auth_kwargs: dictionary of additional args to pass to requests.request()
            ({auth=("username", "password")})
        """

        self.base_url = f"{service_url}/{service_path.strip('/')}/"
        self.requests_auth_kwargs = requests_auth_kwargs
        self.verify_https = verify_https

    def _make_request(self, method: str, path: str, data: dict = None, params: dict = None) -> requests.Response:
        url = self.base_url + path.lstrip("/")
        logger.info(f"Making {method} request to {url}.")

        kwargs = {**self.requests_auth_kwargs, "method": method, "url": url, "verify": self.verify_https}

        if data:
            kwargs["json"] = data
        if params:
            kwargs["params"] = params

        return requests.request(**kwargs)

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

    def validate_local_user(self, username: str, password: str):
        return self._make_request("post", "validate-local-account/", {"username": username, "password": password})

    def validate_sso_user(self):
        pass

    def get_service_metadata(self):
        return self._make_request("get", "metadata/")

    def create_resource(self, data: ResourceRequestBody):
        return self._make_request("post", "resources/", self._get_request_dict(data))

    def get_resource(self, ansible_id):
        return self._make_request("get", f"resources/{ansible_id}/")

    def update_resource(self, ansible_id, data: ResourceRequestBody, partial=False):
        action = "patch" if partial else "put"
        return self._make_request(action, f"resources/{ansible_id}/", self._get_request_dict(data))

    def delete_resource(self, ansible_id):
        return self._make_request("delete", f"resources/{ansible_id}/")

    def list_resources(self, filters: dict = None):
        return self._make_request("get", "resources/", params=filters)

    def get_resource_type(self, name):
        return self._make_request("get", f"resource-types/{name}/")

    def list_resource_types(self, filters: dict = None):
        return self._make_request("get", "resource-types/", params=filters)
