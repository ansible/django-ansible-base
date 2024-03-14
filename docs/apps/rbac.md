# Role-Based Access Control (RBAC)

As a feature of django-ansible-base, this provides access control for already-authenticated users.
Not having access for a specific request sent to the server usually results in a 403 permission denied response.

## Using as an API Client

This section tells how to use the API endpoints as a client;
what requests to make and how to build request data.

You need a server running a Django project that uses this system.
Use test_app in this repo for a demo, see `test_app/README.md` for bootstrap.
http://127.0.0.1:8000/admin/ allows login as admin user (password is "password").

### Create Custom Role (Definition)

After logging in to test_app/, you can visit this endpoint to get the role definition API.

http://127.0.0.1:8000/api/v1/role_definitions/

Perform an OPTIONS request, and you will find this gives choices for
fields `permissions` and `content_type`.
Out of the choices a single `content_type` needs to be chosen for a role definition.
Multiple permissions can be selected, and are accepted in the form of a list.
Type-specific permissions validation is still TBD, these are specific to a model.

A POST to this endpoint will create a new role definition, example data:

```json
{
    "permissions": ["view_inventory"],
    "content_type": "aap.inventory",
    "name": "View a single inventory",
    "description": "custom role"
}
```

Name can be anything string that's not blank. Description can be any string.

### Assigning a User a Role to an Object

Select a role definition from `/api/v1/role_definitions/`, use the id as `role_definition`
and a user from `/api/v1/users/` and use the id as `user`.
Given the type of the role definition, check the available objects of that type,
in this case `/api/v2/inventories/` and obtain the desired id, this will become `object_id`.

With all 3 ids ready, POST to http://127.0.0.1:8000/api/v1/role_user_assignments/

```json
{
    "role_definition": 3,
    "object_id": 3,
    "user": 3
}
```

This will give user id=3 view permission to a single inventory id=3, assuming the role definition
referenced is what was created in the last section.

### Assigning a User as a Member of a Team

While this is possible with the RBAC API, it is not covered here,
because it may come from an external source.

The "member_team" permission may later be prohibited from use in custom role definitions.

### Assigning a Team a Role to an Object

If you used the test_app bootstrap script, then you will find the user "angry_spud"
is a member of the "awx_devs" team.

Assuming the team id is 2, POST to

http://127.0.0.1:8000/api/v1/role_team_assignments/

with data

```json
{
    "role_definition": 3,
    "object_id": 3,
    "team": 2
}
```

This has a similar effect to user assignments, but in this case will give
permissions to all users of a team

### Viewing Assignments

For the single inventory mentioned above, it is possible to view the existing permission
assignments directly to that object.

GET

http://127.0.0.1:8000/api/v1/role_team_assignments/?object_id=3&content_type__model=inventory

http://127.0.0.1:8000/api/v1/role_user_assignments/?object_id=3&content_type__model=inventory

### Revoking an Assignment

From any of the assignment lists, the user can select an assignment to revoke.
Follow the "url" in the serializer from either user or team assignment lists.

DELETE http://127.0.0.1:8000/api/v1/role_user_assignments/1/

Will undo everything related to that assignment.
The user or team's users will lose permission that was granted by the object-role-assignment.

### Assigning Organization Permission

In the case of inventory, its parent object is its organization.
Instead of giving permission to a single inventory, you can use roles to give
permission to all inventories inside of an organization.

The difference in the above steps are that
- when creating a custom role definition the `content_type` would be "shared.organization"
- when creating the assignment, the `object_id` would be the id of an organization

### Displaying Access

To give a complete picture of access, consider that there are 3 "layers" of access.
 - Direct object role assignment - for users and teams
 - Parent object role assignment - for users and teams
 - Superuser or super-auditor user flags

For a single app using this system at the org-level, these 5 distinct pieces
of information would give a complete summary of who has access.
By itself, this does not expand the users who are members of teams.
Assuming that teams-in-teams are enabled, this would not just be the direct
members of the teams, but a listing of all users who have indirect membership to the team.


## Using in a Django Project

These instructions are intended for someone applying this system to an existing Django app.
Start with `docs/Installation.md` for the core ansible_base setup.
The app name is dab_rbac, INSTALLED_APPS path is "ansible_base.rbac".

You can choose to use this entirely at the Django model level
 - you use roles to delegate permissions to users and teams
 - this system will efficiently filter querysets to a certain permission level for a certain user

### Migrations

This is a system applied on top of your app, and uses some of _your_ models
(like user, permissions, etc) in relational fields. dab_rbac lists these models as `swappable_dependences`
which puts your `0001_init` migration as a dependency, but this is likely insufficient.

You should specify `run_before = [('dab_rbac', '__first__')]` in the
last migration of _your_ app at the time you integrate this.
The philosophy of dab_rbac is "outside looking in", and the main link is a loose
link via generic foreign key.
Your permission model is needed to respect your existing permissions setup,
and it needs relational links to your "actor" models (user/team).

### Using in an REST API

Instead of calling methods from DAB RBAC directly, you can connect your
own serializers and views to use Django Rest Framework utilities shipped in DAB.
Permission checking is split into 2 places
 - permission checks for a HTTP verb and endpoint are done in the permission class
 - permission checks for related objects are done in a serializer mixin

To clarify exactly what checks are handled by what, see this table.

 | Action                     | Permission class checks                                  | View/serializer checks                                                                     |
 |----------------------------|----------------------------------------------------------|--------------------------------------------------------------------------------------------|
 | POST / create              | Checking add permission for models with no parent object | Permission to the parent object (like organization)<br>Permission to other related objects |
 | POST for special action    | Checks custom permission to obj                          | nothing                                                                                    |
 | GET detail view            | Checks view permission to object                         | nothing                                                                                    |
 | PUT / PATCH<br>Detail view | Checks edit permission to object                         | Permission to related objects                                                              |
 | DELETE<br>Detail view      | Checks delete permission to object                       | nothing                                                                                    |

Combining these functions, a hypothetical app setup might look like:

```python
from my_app.models import MyModel

from rest_framework import viewsets
from rest_framework import serializers

from ansible_base.rbac.api.related import RelatedAccessMixin
from ansible_base.rbac.api.permissions import AnsibleBaseObjectPermissions


class MyModelSerializer(RelatedAccessMixin, serializers.ModelSerializer):  # (1)
    class Meta:
        model = MyModel
        fields = '__all__'


class MyModelViewSet(viewsets.ModelViewSet):
    permission_classes = [AnsibleBaseObjectPermissions]  # (2)
    serializer_class = MyModelSerializer

    def get_queryset(self):
        return MyModel.access_qs(self.request.user)  # (3)
```

This marks 3 different integration points.
1. `RelatedAccessMixin` - checks access to related objects and gives access to users who create new objects
2. `AnsibleBaseObjectPermissions` - checks object permission for detail views and global "add" permission
3. `MyModel.access_qs` - filters the queryset to only objects the request user has permission to view

### Creating a New Role Definition

Developers should interact with `RoleDefinition` as an ordinary model.
Giving and removing permissions should be handled by methods on a `RoleDefinition` instance.
Ordinarily, the other models from this app should not be interacted with.

NOTE: At various times a "role definition" may be referred to as just a "role".

Roles are expected to be user-defined in many apps. Example of creating a custom role definition:

```
from awx.ansible_base.models.rbac import RoleDefinition

rd = RoleDefinition.objects.get_or_create(name='JT-execute', permissions=['execute_jobtemplate', 'view_jobtemplate'])
```

### Assigning Permissions

With a role definition object like `rd` above, you can then give out permissions to objects.
 - `rd.give_permission(user, obj)` - give permissions listed in `rd` to that user for just that object
 - `rd.remove_permission(user, obj)` - remove permission granted by only that role
 - `rd.give_global_permission(user)` - if configured, give user execute/view permissions to all job templates in the system
 - `rd.remove_global_permission(user)`

These cases assume an `obj` of a model type tracked by the RBAC system,
All the `give_permission` method will return a `RoleUserAssignment` or `RoleTeamAssignment` object.
The `remove_permission` method will return nothing.
Assignments have an associated `object_role` in case you need that.
Removing permission will delete the object role if no other assignments exist.

### Registering Models

Any Django Model (except your user model) can
be made into a resource in the RBAC system by registering that resource in the registry.

```
from awx.ansible_base.utils.permission_registry import permission_registry

permission_registry.register(MyModel, parent_field_name='organization')
```

If you need to manage permissions for special actions beyond the default permissions like "execute", these need to
be added in the model's `Meta` according to the Django documentation for `auth.Permission`.
The `parent_field_name` must be a ForeignKey to another model which is the RBAC "parent"
model of `MyModel`, or `None`.

TODO: Update to allow ManyToMany parent relationship in addition to ForeignKey
https://github.com/ansible/django-ansible-base/issues/78

#### Django Model, Apps, and Permission Constraints

It is fine to register models from multiple apps, but among the registered models,
the `._meta.model_name` must be unique. If, in the above example,
you registered `my_app.mymodel` then it is fine if other models by that same
name exist like `your_app.mymodel`, but _registering both_ models will throw an error.

A similar constraint exists for the permission `codename`.
If the `Meta` of `MyModel` lists `permissions = [("move", "Can move my model")]`,
then no other _registered_ model should list that permission.

This rules out things like registering a model, and also registering a proxy
model _of that model_.

### Parent Resources

Assuming `obj` has a related `organization` which was declared by `parent_field_name` when registering,
you can give and remove permissions to all objects of that type "in" the organization
(meaning they have that ForeignKey to the organization).
- `rd.give_permission(user, organization)` - give execute/view permissions to all job templates in that organization
- `rd.remove_permission(user, organization)` - revoke permissions obtained from that particular role (other roles will still be in effect)

### Evaluating Permissions

The ultimate goal of this system is to evaluate what objects a user
has a certain type of permission to (access control).
Given a registered model, you can do these things.

- obtain visible objects for a user with `MyModel.access_qs(user, 'view_mymodel')`
- obtain objects user has permission to delete `MyModel.access_qs(user, 'delete_mymodel')`
- determine if user can delete one specific object `user.has_obj_perm(obj, 'delete_mymodel')`
- use only the action name for a queryset shortcut `MyModel.access_qs(user, 'view')`
- get visible objects, view permission implied `MyModel.access_qs(user)`
- use only the action name or object permission check `user.has_obj_perm(obj, 'delete')`
- efficient filtering of related model `RelatedModel.objects.filter(mymodel=MyModel.access_ids_qs(user))`

Some HTTP actions will be more complicated. For instance, if you create a new object that combines
several related objects and each of those related objects require "use" permission.
Those cases are expected to make multiple calls to methods like `has_obj_perm` within the
API code, including views, permission classes, serializer classes, templates, forms, etc.

### Creator Permissions

You can give a user "add" permission to a parent model, like "add_mymodel".
The Django `Permission` entry links to the content type for `MyModel`,
but these permissions can only apply to the parent model of the object,
or act as system-wide permissions.
After a user creates an object, you need to give the user creator permissions.
Otherwise they won't even to be able to see what they created!

```
RoleDefinition.objects.give_creator_permissions(user, obj)
```

This will assign all valid permissions for the object they created from the
list in `settings.ANSIBLE_BASE_CREATOR_DEFAULTS`. Not all entries in this will apply to
all models.

```
ANSIBLE_BASE_CREATOR_DEFAULTS = ['change', 'execute', 'delete', 'view']
```

### Django Settings for Swappable Models

You can specify which model you want to use for Organization / User / Team / Permission models.
The user model is obtained from the generic Django user setup, like the `AUTH_USER_MODEL` setting.

CAUTION: these settings will be used in _migrations_ and changing them later on can be hazardous.

```
ANSIBLE_BASE_TEAM_MODEL = 'auth.Group'
ANSIBLE_BASE_ORGANIZATION_MODEL = 'main.Organization'
```

The organization model is only used for pre-created role definitions.

### Managed Pre-Created Role Definitions

In a post_migrate signal, certain RoleDefinitions are pre-created.
You can customize that with the following setting.

```
ANSIBLE_BASE_ROLE_PRECREATE = {
    'object_admin': '{cls._meta.model_name}-admin',
    'org_admin': 'organization-admin',
    'org_children': 'organization-{cls._meta.model_name}-admin',
    'special': '{cls._meta.model_name}-{action}',
}
```

Set this to `{}` if you will create role definitions in your own data migration,
or if you want all roles to be user-defined.

### RBAC vs User Flag Responsibilities

With some user flags, like the standard `is_superuser` flag, the RBAC system does not
need to be consulted to make an evaluation.
You may or may not want this to be done as part of the attached methods
like `access_qs` or `has_obj_perm`. That can be controlled with these.

```
ANSIBLE_BASE_BYPASS_SUPERUSER_FLAGS = ['is_superuser']
ANSIBLE_BASE_BYPASS_ACTION_FLAGS = {'view': 'is_system_auditor'}
```

You can blank these with values `[]` and `{}`. In these cases, the querysets
will produce nothing for the superuser if they have not been assigned any roles.

### Global Roles

Global roles have very important implementation differences compared to object roles.
A role definition must have `content_type` set to `None` in order to be assigned globally.
You can use the `RoleDefinition.give_global_permission` methods to assign a role globally.
This means the user or team receiving this permission will have the role's permissions
regardless of the particular object involved.

This could give permission to do an action (like view) to all objects of a certain
type (like inventory) in the system.
It can also give permission in cases where no object is involved.
For instance, if a model `Instance` is not associated with an organization because
they are considered global, then an `add_instance` permission could allow someone
to add an inventory. No parent object is involved.
This applies to organizations, where `add_organization` can be used to give
non-superusers the ability to create an organization.

Global roles are not cached in the `RoleEvaluation` table.
This means that if you're creating a display of users who have access to an object,
global roles require special consideration.

### Enablement of Features

There are a number of settings following the naming `ANSIBLE_BASE_ALLOW_*`.
These will enable or disable a certain thing. Suffixes are listed below:

 - TEAM_PARENTS - whether to allow giving roles to teams that give membership to other teams
 - TEAM_ORG_PERMS - whether to allow giving teams Organization-wide permissions
 - TEAM_ORG_ADMIN - whether to allow giving teams Organization-wide permissions which include memberships to other teams
 - CUSTOM_ROLES - whether to allow creation of custom roles at all
 - CUSTOM_TEAM_ROLES - whether to allow creation of custom roles that apply to teams (which could be confusing)
 - SINGLETON_USER_ROLES - whether to allow giving system-wide roles to users, incurs 1 additional query for evaluations
 - SINGLETON_TEAM_ROLES - whether to allow giving system-wide roles to teams, incurs 1 additional query for evaluations
 - SINGLETON_ROLES_API - whether to allow creating system-wide roles via the API

If you create (in code) a role definition that sets `managed` to True, then these
rules will be disregarded for that particular role definition. Managed role
definitions can not be created through the API, but can be created in code like migration scripts.

### Tracked Relationships

Let's say that you are introducing RBAC, and you have already set up your API
with some relationship, like members of a team, and parents of a team
(to get nested teams).
This sub-feature will use signals to do bidirectional syncing of memberships of
that relationship with memberships of their corresponding role.

```
permission_registry.track_relationship(Team, 'tracked_users', 'team-member')
permission_registry.track_relationship(Team, 'team_parents', 'team-member')
```

This only works with our 2 "actor" types of users and teams.
Adding these lines will synchronize users and teams of team-object-roles with the "team-member"
role definition (by name) to the `Team.tracked_users`
and `Team.tracked_parents` ManyToMany relationships, respectively.
So if you have a team object, `team.tracked_users.add(user)` will also give that
user _member permission_ to that team, where those permissions are defined by the
role definition with the name "team-member".

## System Design Principles

This is derived from the RBAC system in AWX which was implemented roughly
in the year 2015, and this remained stable until an overhaul, with early work
proceeding in the year 2023.

The 2015 implementation had the following key distinguishing features:
 - object roles were auto-created when a resource was created
 - roles formed an acyclic (or cyclic) graph between each other via their parents and children
 - object roles were defined by the `ImplicitRoleField` declared on each model
 - teams gain permission by adding their `member_role` to parents of another role

The key differences of the 2023 system are:
 - object roles are not auto-created, but only created as needed to perform assignments
 - resources are organized in a strict tree, mostly with organizations being the parents
 - role definitions list canonical Django Permission objects
 - teams are listed in a `role.teams.all()` relationship directly, similar to users

The main _commonality_ between the two systems is that Django signals are used to cache
information that includes 3 bits of information (content_object, permission, object-role),
and then this information is used to produce querysets of objects that a certain user
has a certain permission for. This is done by matching object-roles to the object-roles
the user has been given.

Cached information allows for scaling a deep, rich, permission assigning system
without performance death-spiral of querysets.

### What Constitutes a Graph?

The 2015 system, by auto-creating roles, was able to map roles directly to other roles
to define parents and children. This also allowed highly specific inheritance paths
along the lines of specific permissions... imagine an "inventory_admin" role
giving read permissions to all the job templates that used that inventory.

Through the years when this system was in use, the inheritance rarely mapped
from one type of permission to a different permission like the example.

Because of this, `ObjectRole`s in the 2023 system don't have the same parent/child
link to other roles. But there are still two types of graphs at work:
 - Resources have parent resources, and could be drawn out as a tree structure
 - Teams can have member permissions to other teams

### System-Wide Roles

The 2015 system treated the system admin and system auditor as system roles.
However, because the role ancestors are cached for each role, this meant that
every role had a link to the system admin role. To some extent, this threw cold
water on adding more system roles. The storage and additional caching overhead
for system roles did not encourage use of more system roles.

Ultimately, system roles do not need caching like object roles do.
The querysets do not get out-of-control for the task of returning
the permissions a user has. Nesting inside of more complex queries still can.
Because of that, a method for handling system roles with an _entirely separate_
system is offered here that hooks into the same bound methods as the object-role system.

## Models

These models represent the underlying RBAC implementation and generally will be abstracted away from your daily development tasks by signals connected by the permission registry.

You should also prefer to use the attached methods when possible.
Those have some additional syntax aids, validation, and can take the user flags
and the global roles system into account.

### `ObjectRole`

`ObjectRole` is an instantiation of a role definition for a particular object.
The `give_permission` method creates an object role if one does not exist for that (object, role definition)

#### `descendent_roles()`

For a given object role, if that role offers a "member_team" permission, this gives all
the roles that are implied by ownership of this role.

For object roles that do not offer that permission, or do not apply to a team
or a team's parent objects, this should return an empty set.

#### `needed_cache_updates()`

This shows the additions and removals needed to make the `RoleEvaluation` correct
for the particular `ObjectRole` in question.
This is used as a part of the re-computation logic to cache role-object-permission evaluations.

### `RoleEvaluation`

`RoleEvaluation` gives cached permission evaluations for a role.
Each entry tells you that ownership in the linked `role` field confers the
permission listed in the `codename` field to the object defined by the
fields `object_id` and `content_type_id`.

This is used for generating querysets and making role evaluations.

This table is _not_ the source of truth for information in any way.
You can delete the entire table, and you should be able to re-populate it
by calling the `compute_object_role_permissions()` method.

Because its function is querysets and permission evaluations, it has
class methods that serve these functions.
Importantly, these consider _indirect_ permissions given by parent objects,
teams, or both.

#### `accessible_ids(cls, user, codename)`

Returns a queryset which is a values list of ids for objects of `cls` type
that `user` has the permission to, where that permission is given in `codename`.

This is lighter weight and more efficient than using `accessible_objects` when it is needed
as a subquery as a part of a larger query.

#### `accessible_objects(cls, user, codename)`

Return a queryset from `cls` model that `user` has the `codename` permission to.

#### `get_permissions(user, obj)`

Returns all permissions that `user` has to `obj`.
