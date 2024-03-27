# Ansible Resource Registry

## Setup

### App Setup
Add `ansible_base.resource_registry` to your installed apps:

```
INSTALLED_APPS = [
    ...
    'ansible_base.resource_registry',
]
```

### Configure the Resource List

Create a new python module which defines an `APIConfig` class and `RESOURCE_LIST` set:

``` python
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from ansible_base.authentication.models import Authenticator
from ansible_base.resource_registry.registry import ResourceConfig, ServiceAPIConfig, SharedResource
from ansible_base.resource_registry.shared_types import TeamType, UserType


class APIConfig(ServiceAPIConfig):
    service_type = "aap"


RESOURCE_LIST = (
    ResourceConfig(get_user_model(), shared_resource=SharedResource(serializer=UserType, is_provider=True), name_field="username"),
    ResourceConfig(
        Group,
        shared_resource=SharedResource(serializer=TeamType, is_provider=True),
    ),
    ResourceConfig(Authenticator),
)
```

`APIConfig.service_type` must be one of "awx", "galaxy" or "eda".

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

#### Customization

The `APIConfig` additionally allows service maintainers to customize how specific resource types are serialized and saved. This can be helpful if the
version of the resource that the application has locally doesn't have the same fields as a shared serializer.

```python
class UserProcessor(ResourceTypeProcessor):
    def pre_serialize_additional(self):
        # Set any non standardized attributes on the resource before serialization.
        # This gets called before the additional data serializer serializes the instance.
        setattr(self.instance, "external_auth_provider", None)
        setattr(self.instance, "external_auth_uid", None)
        setattr(self.instance, "organizations", [])
        setattr(self.instance, "organizations_administered", [])

        return self.instance

    def pre_serialize(self):
        # Set any non standardized attributes on the resource before serialization.
        # This gets called before the resource type serializer serializes the instance.

        setattr(self.instance, "is_system_auditor", self.instance.has_role("system_auditor"))
        return self.instance

    def pre_save(self, validated_data, is_new=False):
        if validated_data["is_system_auditor"]:
            self.instance.add_role("system_auditor")
        super().save(validated_data, is_new=is_new)

class APIConfig(ServiceAPIConfig):
    # Set custom processors with this dictionary.
    custom_resource_processors = {"shared.user": UserProcessor}
    service_type = "aap"
```

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

## Fields

### AnsibleResourceField

This allows developers to add a reverse one to one relation from a model to the Resources table. This field acts like any other foreign key or one to one field, but does not create new migrations or add any new columns to the table.

Usage:

```
from ansible_base.resource_registry.fields import AnsibleResourceField

class Organization(AbstractOrganization):
    resource = AnsibleResourceField(primary_key_field="id")
```

Once the field is declared, you can interact with it like any other foreign key or one to one field:

Reference the `.resource` property:
```
In [2]: Organization.objects.first().resource
Out[2]: <Resource: Resource object (3)>

In [3]: Organization.objects.first().resource.ansible_id
Out[3]: '0cdae8c9:1e25c31c-6002-478a-bc8f-7d982288cf5d'
```

Use `.select_related` to join tables:
```
In [7]: for org in Organization.objects.select_related("resource").all():
   ...:     print(org.resource.ansible_id)

0cdae8c9:1e25c31c-6002-478a-bc8f-7d982288cf5d
0cdae8c9:bb6b4aec-2215-4694-9a9e-fcee886977e2
```

Filter on `resource`:
```
In [9]: Organization.objects.get(resource__resource_id="bb6b4aec-2215-4694-9a9e-fcee886977e2").name
Out[9]: 'test2'
```

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

### service-index/resource-types/{name}/manifest/

This returns a manifest of the current state of resources on RESOURCE_SERVER, the manifest is presented as a streamed HTTP
response with a CSV containing columns `resource_id` and `resource_hash`, `resource_hash` is the sha256 calculated
from the Resource.resource_data serialized by the ResourceSerializer.

This endpoint allows each service to check the state of RESOURCE_SERVER and perform comparisons with its local resources to
perform sync operations (create, update, delete).

```csv
ansible_id,resource_hash,modified
31daab14-cb67-4c62-8dcd-39f411c82242,6c78ee32d146a01bc22902a36dbced5af6ec0563c6d190491ad1262ef53dc6ed,2024-05-13 19:17:50.223497+00:00
97447387-8596-404f-b0d0-6429b04c8d22,86f06a619dd768393c4969f725bae089a265168fb79f1fdcac2d4442e41ac529,2024-05-13 19:17:52.610575+00:00
4d01427e-a11e-4d0e-9408-4ef7c2b478d6,7e1fcf1993a9f84865745ecd923b68b589448c6a34e91407d690f4868d132797,2024-05-15 17:38:35.882268+00:00
53886798-29e7-426f-b9cb-f7f74b346072,9ed7b1707a3e2787ba1fde5e1b4bac98173befaf25f1e1210e66d18f00602330,2024-05-15 17:39:39.580444+00:00

```

### Syncing local services with RESOURCE_SERVER Resources

Each service connected to the RESOURCE_SERVER can schedule a sync process, this process can
be done via the management command `resource_sync` or by wrapping the `tasks.sync.SyncExecutor().run()`
in a main task and spawning any tasking system that the service uses.

The sync will be performed only for resources managed by APP, those which `service_id`
matched the RESOURCE_SERVER `service_id`, local managed resources will not be affected.

> IMPORTANT: Syncs must happen after initial resource migration is performed.


#### How Resource Sync works

The sync process consists in:

0. Fetch the remote manifest from APP
0. Based on the remote manifest, cleanup orphaned managed resources from local service
0. Iterate over resources organization, team, user
    - Order matters, orgs must be created before team and so on.
0. for each resource in manifest compare the remote hash with local hash
    - If equal: No Operation, status NOOP
    - If different: Update local with remote data, status UPDATED
    - If not found locally, create: status CREATED
    - If cannot create or update locally, status CONFLICT
    - If remote resource data cannot be fetched, status UNAVAILABLE
0. Resilience:
    - If during the execution of sync the RESOURCE_SERVER server is offline or a resource
      from the manifest cannot be found, then it is marked as UNAVAILABLE and
      the caller can accumulate it for a retry strategy, the management
      command `resource_sync` implements a retry default to 3 attempts.

#### Configuration

Resource Sync depends on a `ResourceAPIClient` that can be instantiated and passed
to `SyncExecutor` or automatically created based on the configuration from
the `django.conf.settings` that looks like.

```python
RESOURCE_SERVER = {
    "URL": "https://localhost",
    "SECRET_KEY": "<VERY-SECRET-KEY-HERE>",
    "VALIDATE_HTTPS": False,
}
RESOURCE_JWT_USER_ID = "97447387-8596-404f-b0d0-6429b04c8d22"
RESOURCE_SERVICE_PATH = "/api/server/v1/service-index/"
```

> NOTE: Secret key must be generated on the resource server, e.g `generate_service_secret` management command.

#### Running Resource Sync as a Command

Resources can be synced via the management command `resource_sync`, this is useful
for scheduling execution on a scheduler such as cron.

> NOTE: The argument `--asyncio` enables asyncio executor, it is recommended when the system
> has a large number os resources, for a system with small number of resources or to debug
> the sync command this argument can be omitted.


```console
$ django-admin resource_sync --asyncio

----- RESOURCE SYNC STARTED -----

>>> shared.organization
Deleting 1 orphaned resources
Processing 2 resources with asyncio executor.
CREATED 3e3cc6a4-72fa-43ec-9e17-76ae5a3846ca Acme
NOOP 3e3cc6a4-72fa-43ec-9e17-76ae5a389999
Processed 3 | Created 1 | Updated 0 | Conflict 0 | Unavailable 0 | Skipped 1 | Deleted 1

>>> shared.team
Processing 1 resources with asyncio executor.

NOOP f43938cf-a618-4a73-bc90-922a6b217e4d
CREATED f43938cf-a618-4a73-bc90-922a6b28888
Processed 2 | Created 1 | Updated 0 | Conflict 0 | Unavailable 0 | Skipped 1 | Deleted 0

>>> shared.user
Processing 4 resources with asyncio executor.

UPDATED 31daab14-cb67-4c62-8dcd-39f411c82242 joe
NOOP 97447387-8596-404f-b0d0-6429b04c8d22
NOOP 4d01427e-a11e-4d0e-9408-4ef7c2b478d6
CONFLICT 53886798-29e7-426f-b9cb-f7f74b346072 mary
Processed 4 | Created 0 | Updated 1 | Conflict 1 | Unavailable 0 | Skipped 2 | Deleted 0

----- RESOURCE SYNC FINISHED -----
```

The output of the command is useful for when it is executed interactively,
on a scheduled cronjob it is recommended to redirect the descriptors to a log file.

```console
# prints and errors to the log file
$ django-admin resource_sync --asyncio &>> /path/to/resource_sync.log

# or send just the stdout to the void
$ django-admin resource_sync --asyncio > /dev/null
```

##### Statuses

```console
NOOP 193f1478-5f81-41f3-8355-47db5e8de889
CONFLICT 518627b7-827d-47c3-813c-4b479c4855d0
CONFLICT 4e31d6c4-823b-429d-bd44-b16aece348bb
```

As shown above, status will be printed before each resource ansible_id,
the statuses are:

- **NOOP**
    - RESOURCE_SERVER remote resource is equal to local resource, nothing to do.
- **CREATED**
    - Resource does not exist locally, attempt to create it.
- **UPDATED**
    - Local resource differs from remote, update it with remote data.
- **UNAVAILABLE**
    - There were a failure trying to fetch resource_data from remote.
    - This may happen when RESOURCE_SERVER api is temporarily unavailable or
      resource was deleted from remote while sync was running.
- **CONFLICT**
    - An attempt to CREATE or UPDATE the resource locally ended on a conflict
      commonly a unique constraint error when a local unmanaged resource has the
     same name, username, email etc...

##### Retrying

All the attempts to sync that returns `UNAVAILABLE` are queued for retry,
the default retry attempts are 3 and the interval are 30 seconds.

to customize it pass `--retries` and `--retrysleep`.

```console
$ django-admin resource_sync --retries 3 --retrysleep 60

----- RESOURCE SYNC STARTED -----
...
Processing shared.user
3 items to process
Deleting orphaned managed resources
10 orphaned managed resources deleted
Processing with asyncio executor
UNAVAILABLE 193f1478-5f81-41f3-8355-47db5e8de889
CONFLICT 518627b7-827d-47c3-813c-4b479c4855d0
CONFLICT 4e31d6c4-823b-429d-bd44-b16aece348bb
----- RESOURCE SYNC FINISHED -----
Processed 3 | Created 0 | Updated 0 | Conflict 2 | Unavailable 1 | Skipped 0 | Deleted 10
Retry attempt 0/3
waiting 60 seconds
UNAVAILABLE 193f1478-5f81-41f3-8355-47db5e8de889
----- RESOURCE SYNC FINISHED -----
Processed 1 | Created 0 | Updated 0 | Conflict 0 | Unavailable 1 | Skipped 0 | Deleted 0
Retry attempt 1/3
waiting 60 seconds
UNAVAILABLE 193f1478-5f81-41f3-8355-47db5e8de889
----- RESOURCE SYNC FINISHED -----
Processed 1 | Created 0 | Updated 0 | Conflict 0 | Unavailable 1 | Skipped 0 | Deleted 0
Retry attempt 2/3
waiting 60 seconds
UPDATED 193f1478-5f81-41f3-8355-47db5e8de889
----- RESOURCE SYNC FINISHED -----
Processed 1 | Created 0 | Updated 1 | Conflict 0 | Unavailable 0 | Skipped 0 | Deleted 0
```

##### Syncing a specific resource_type

Command accepts optional positional arguments

```console
$ django-admin resource_sync shared.user # sync only user type
$ django-admin resource_sync user  # prefix can be omited

$ django-admin resource_sync organization user  # only org and user

$ django-admin resource_sync organization team user  # every type
# the above is the default if not passed.
```

> BEWARE: Orgs and teams must be synced before users.

#### Implementing Resource Sync on a custom tasking system.

Each service can opt to execute resource sync using its preferred way of task scheduling,
the module `tasks/sync.py` provides a `SyncExecutor` class with a `run` method.

Example:

```python
from celery import Celery
from celery.schedules import crontab
from ansible_base.resource_registry.tasks.sync import SyncExecutor

# Initialize Celery app
celery = Celery('your_app_name', broker='redis://localhost:6379/0')

# Define Celery task
@celery.task
def execute_sync_executor():
    SyncExecutor(
        asyncio=False,
        api_client=ResourceAPIClient(....),  # Omit to have a default client created
        retries=3,
        retrysleep=60,
        retain_seconds=300,  # Avoid delete resources created in the latest 5 minutes
        stdout=sys.stdout  # omit to silence it
    ).run()

# Schedule the task to run every 15 minutes
celery.conf.beat_schedule = {
    'execute-every-15-minutes': {
        'task': 'your_module.execute_sync_executor',
        'schedule': crontab(minute='*/15'),
    },
}

# Optional configuration to store results
celery.conf.result_backend = 'redis://localhost:6379/0'
```

#### Alternative sync executor

Alternatively the functions on the `tasks/sync.py` can be composed to create a custom sync executor.

Important details:

- No transaction handling is performed, each implementation must take care of it,
  beware that django atomic transactions doesn't work if using async runners.
- No exception handling is performed, errors like HTTPError will bubble up.
- No retrying is in place, the function just return the status of each resource
  it is up to the implementation how the retry will be performed.

Functions exposed on `tasks/sync.py`

- `create_api_client() -> ResourceAPIClient`
- `fetch_manifest(name, api_client) -> list[ManifestItem]` - Fetches and parses RESOURCE_SERVER resource manifest endpoint
- `cleanup_deleted_managed_resources(name, manifest_list) -> int` - Deletes orphaned resources present on local system
- `resource_sync(manifest_item, api_client) -> SyncResult` - Compare and Sync resource
- `async_resource_sync` - Awaitable version of the above

Objects and types:

- `SyncStatus` enum with variantes for `CREATED,UPDATED,NOOP,UNAVAILABLE,CONFLICT`
- `SyncResult` type containing status and item
- `ManifestItem` - Serializer for resource manifest CSV containing ansible_id and resource_hash
- `ResourceTypeName` - Iterable enum containing variants `shared.{organization,team,user}`
- `ManifestNotFound` - Custom exception for when manifest is not served
