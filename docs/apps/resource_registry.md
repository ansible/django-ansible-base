# Ansible Resource Registry

## Setup

### App Setup
Add `ansible_base.resource_registry` to your installed apps and set the name of the local service.

```
INSTALLED_APPS = [
    ...
    'ansible_base.resource_registry',
]

ANSIBLE_BASE_SERVICE_PREFIX = 'my_app'
```

The name of the local service will prefix model names for local resources.
An inventory model will be referred to as "my_app.inventory" in this example.
The local service must be one of "local" (placeholder), "aap", "awx", "galaxy" or "eda".

### Configure the Resource List

Create a new python module which defines an `APIConfig` class and `RESOURCE_LIST` set:

``` python
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from ansible_base.authentication.models import Authenticator
from ansible_base.resource_registry.registry import ResourceConfig, ServiceAPIConfig, SharedResource
from ansible_base.resource_registry.shared_types import TeamType, UserType


class APIConfig(ServiceAPIConfig):
    pass


RESOURCE_LIST = (
    ResourceConfig(get_user_model(), shared_resource=SharedResource(serializer=UserType, is_provider=True), name_field="username"),
    ResourceConfig(
        Group,
        shared_resource=SharedResource(serializer=TeamType, is_provider=True),
    ),
    ResourceConfig(Authenticator),
)
```

`RESOURCE_LIST` must be a list or set of `ResourceConfig` objects. This object defines a model to be included in the resource registry, as well
as a set of metadata from that resource. Right now it accepts the following args:

- `model`: the model to register as a resource

and the following kwargs:

- `shared_resource`: `namedtuple("SharedResource", ["serializer", "is_provider"])`. `serializer` is the serializer class instance for this resource.
  It should be set to one of the serializers in ansible_base.resource_registry.shared_types. `is_provider` should be set to true if the service
  is the source of truth for the resource.
- `name_field`: the field on the model to be used as the object's name. This defaults to `name`.
- `parent_resources`: List of `namedtuple("ParentResource", ["model", "field_name"])`. This is to be used with RBAC, but is not currently implemented.

Once this model is provided, register it in settings.py by setting `ANSIBLE_BASE_RESOURCE_CONFIG_MODULE`, ex: `ANSIBLE_BASE_RESOURCE_CONFIG_MODULE = "test_app.resource_api"`

### Add the Resource API URLs

```python
from ansible_base.resource_registry.urls import urlpatterns as resource_api_urls

urlpatterns = [
    ...,
    path('api/v1/', include(resource_api_urls)),
]
```

This will add the following paths:

- `service-index/resources/`: list of available resources.
- `service-index/resource-types/`: list of available resource types.
- `service-index/metadata/`: service metadata (service type and ID)

## Models

### ServiceID

This contains a UUID that identifies the system. This UUID is generated at migration time and cannot be changed.

### ResourceType

This is an extension of the ContentType model that adds some additional metadata. These are created from the `RESOURCE_LIST` configured above via a post migration signal.

Resource Types are named using the following convention: `<service_type>:<model_name>` where service type is defined in the `APIConfig` object. Shared resources are prefixed with `shared` instead of the service type.

### Resource

Resources are generic foreign keys to other models in the system that are given a unique Ansible ID. These are created via a post migration signal and kept up to date via `post_delete` and `post_save` signals.

#### Ansible ID

Ansible IDs are unique identifiers for a resource. They are are made up of two parts: the first portion of the service's ID and a UUIDv4 that is generated for each resource. They follow the pattern: `SSSSSSSS:RRRRRRRR-RRRR-RRRR-RRRR-RRRRRRRRRRRR` where `S` is the service short ID and `R` is the resource UUID.

Examples:
- `4c4ef945:faed95ca-2cea-43d4-ae18-4a5f0782a5de`
- `4c4ef945:d26824bf-2764-48b6-a31e-f22364e47332`
- `4c4ef945:66f5e7ae-5e30-465b-9312-a69fd8aa2661`

## APIs

The resource APIs are intended to be served from the applications primary API (ex: `/api/v2/service-index/`).

### service-index/resources/

This is a CRUD view for all the registered resources in the system. It supports list/retrieve for all resources and create/update/delete operations for resources that:

1. Declare a serializer
2. Are managed by another service

Resources that are managed by another services are once that have the `shared_resource.is_provider=True` flag.

``

#### List, Retrieve Operations

The list view displays resource metadata for each resource in the system:

```json
{
    "object_id": "2",
    "name": null,
    "ansible_id": "4c4ef945:faed95ca-2cea-43d4-ae18-4a5f0782a5de",
    "resource_type": "aap.servicecluster",
    "has_serializer": false,
    "detail_url": "/api/galaxy/v1/service_clusters/2/",
    "url": "/api/galaxy/service-index/resources/4c4ef945:faed95ca-2cea-43d4-ae18-4a5f0782a5de/"
}
```

The retrieve view can also display some resource data if a serializer is declared on the resource:

```json
{
    "object_id": "1",
    "name": "admin",
    "ansible_id": "4c4ef945:57289235-e68e-4abf-8e50-f868f9e5ff04",
    "resource_type": "shared.user",
    "has_serializer": true,
    "resource_data": {
        "username": "admin",
        "email": "admin@localhost",
        "first_name": "",
        "last_name": "",
        "is_superuser": true
    },
    "detail_url": "/api/galaxy/v1/users/1/",
    "url": "/api/galaxy/service-index/resources/4c4ef945:57289235-e68e-4abf-8e50-f868f9e5ff04/"
}
```

#### Create, Update, Delete Operations

CUD operations are only allowed from clients with the correct level of permissions on this API. They are intended to be used by an external system to manage the data in this service. All other clients must use the existing REST APIs.

To create a resource, you need to declare the resource type and provide the data for the resource:

```
POST

{
    "resource_type": "shared.organization",
    "resource_data": {"name": "my org"}
}
```

Resource data is determine by the serializer declared in `shared_resource.serializer`.

An ansible ID can also be specified when creating a resource by including it in the request body. By default a new ID will be created for new resources.

```
POST

{
    "ansble_id": "4c4ef945:57289235-e68e-4abf-8e50-f868f9e5ff04",
    "resource_type": "shared.organization",
    "resource_data": {"name": "my org"}
}
```

Delete and Update operations function the same as any other DRF API calls.

### service-index/resource-types/

This purely a list and retrieve view. It displays all the resource types that are available in the system:

```json
{
    "count": 1,
    "next": null,
    "previous": null,
    "results": [
        {
            "id": 1,
            "name": "shared.organization",
            "externally_managed": false,
            "shared_resource_type": "organization",
            "url": "/api/galaxy/service-index/resource-types/shared.organization/"
        }
    ]
}
```

### service-index/metadata/

This displays information about the service itself:

```json
{
    "service_id": "4c4ef945-ae71-48de-ade0-50cb5fe5580d",
    "service_type": "aap"
}
```
