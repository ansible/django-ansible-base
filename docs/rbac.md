# Role-Based Access Control (RBAC)

This intended for a developer audience, for applying this system to a Django app.

This is derived from the RBAC system in AWX which was implemented roughly
in the year 2015, and this remained stable until an overhaul, with early work
proceeding in the year 2023.

## Using

Start with `docs/Installation.md` for the core ansible_base setup.

### RBAC Usage at ORM layer

Developers should interact with `RoleDefinition` as an ordinary model.
Giving and removing permissions should be handled by methods on a `RoleDefinition` instance.
Ordinarily, the other models from this app should not be interacted with.

NOTE: At various times a "role definition" may be referred to as just a "role".
Grammatically, we prefer to refer to an object role
(association of a role definition with an object) as a "object-role" to avoid ambiguity.
The 2015 system referred to object-roles as "roles".

#### Creating a New Role Definition

Roles are expected to be user-defined in many apps. Example of creating a custom role definition:

```
from awx.ansible_base.models.rbac import RoleDefinition

rd = RoleDefinition.objects.get_or_create(name='JT-execute', permissions=['execute_jobtemplate', 'view_jobtemplate'])
```

#### Assigning Permissions

With a role definition object like `rd` above, you can then give out permissions to objects.
 - `rd.give_permission(user, obj)` - give permissions listed in `rd` to that user for just that object
 - `rd.remove_permission(user, obj)` - remove permission granted by only that role
 - `rd.give_global_permission(user)` - if configured, give user execute/view permissions to all job templates in the system
 - `rd.remove_global_permission(user)`

These cases assume an `obj` of a model type tracked by the RBAC system,
All the `give_permission` and `remove_permission` methods will return an `ObjectRole` specific to `obj`, if applicable.
Removing permission will delete the object role if no other assignments exist.

#### Registering Models

Any Django Model (except your user model) can
be made into a resource in the RBAC system by registering that resource in the registry.

```
from awx.ansible_base.utils.permission_registry import permission_registry

permission_registry.register(MyModel, parent_field_name='organization')
```

If you need to manage special permissions beyond the default permissions like "execute", these need to
be added in the model's `Meta` according to the Django documentation for `auth.Permission`.
The `parent_field_name` must be a ForeignKey to another model which is the RBAC "parent"
model of `MyModel`, or `None`.

#### Parent Resources

Assuming `obj` has a related `organization` which was declared by `parent_field_name` when registering,
you can give and remove permissions to all objects of that type "in" the organization
(meaning they have that ForeignKey to the organization).
- `rd.give_permission(user, organization)` - give execute/view permissions to all job templates in that organization
- `rd.remove_permission(user, organization)` - revoke permissions obtained from that particular role (other roles will still be in effect)

#### Evaluating Permissions

For a registered model, you can obtain visible objects for a user with
a method automatically attached `MyModel.accessible_objects(user, 'view_mymodel')`.
This is not restricted to view permissions, you could give a queryset of
all objects the user can delete via `MyModel.accessible_objects(user, 'delete_mymodel')`.

If you can produce a queryset, then you can make a permission evaluation.
However, a bound method to the user model is provided as a shortcut
via `user.has_obj_perm(obj, 'delete_mymodel')`.

#### Creator Permissions

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
list in `settings.ROLE_CREATOR_DEFAULTS`. Not all entries in this will apply to
all models.

```
ROLE_CREATOR_DEFAULTS = ['change', 'execute', 'delete', 'view']
```

### Django Settings and Features

You can specify which model you want to use for Organization / User / Team / Permission models.
The user model is obtained from the generic Django user setup, like the `AUTH_USER_MODEL` setting.

CAUTION: these settings will be used in _migrations_ so if you change these
settings later on, you will need to handle that in a new migration.

```
ROLE_TEAM_MODEL = 'auth.Group'
ROLE_ORGANIZATION_MODEL = 'main.Organization'
ROLE_PERMISSION_MODEL = 'auth.Permission'
```

The organization model is only used for pre-created role definitions.

#### Managed Pre-Created Role Definitions

In a post_migrate signal, certain RoleDefinitions are pre-created.
You can customize that with the following setting.

```
GATEWAY_ROLE_PRECREATE = {
    'object_admin': '{cls._meta.model_name}-admin',
    'org_admin': 'organization-admin',
    'org_children': 'organization-{cls._meta.model_name}-admin',
    'special': '{cls._meta.model_name}-{action}',
}
```

Set this to `{}` if you will create role definitions in your own data migration,
or if you want all roles to be user-defined.

#### RBAC vs User Flag Responsibilities

With some user flags, like the standard `is_superuser` flag, the RBAC system does not
need to be consulted to make an evaluation.
You may or may not want this to be done as part of the attached methods
like `accessible_objects` or `has_obj_perm`. That can be controlled with these.

```
ROLE_BYPASS_SUPERUSER_FLAGS = ['is_superuser']
ROLE_BYPASS_ACTION_FLAGS = {'view': 'is_system_auditor'}
```

You can blank these with values `[]` and `{}`. In these cases, the querysets
will produce nothing for the superuser if they have not been assigned any roles.

#### Global Roles

Global roles have very important implementation differences compared to object roles,
and are not enabled by default. You must declare a ManyToMany relationship that exists
in your user and/or team model to be able to give a role globally.

```
ROLE_SINGLETON_USER_RELATIONSHIP = 'global_roles'
ROLE_SINGLETON_TEAM_RELATIONSHIP = 'global_roles'
```

With this, you could call `user.global_roles.add(rd)` or `team.global_roles.add(rd)`
for that user or team to get the global permission offered by the role definition.
The `rd.give_global_permission(user)` does the same thing but also clears cached values.

You can view a user's global permissions from `user.singleton_roles()`.
Global roles will affect the outcome of `user.has_obj_perm` and `MyModel.accessible_objects` calls.
This is similar to configuring the user flags bypass.

#### Tracked Relationships

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

### System Design Principles

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

#### What Constitutes a Graph?

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

#### System-Wide Roles

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

### Models

These models represent the underlying RBAC implementation and generally will be abstracted away from your daily development tasks by signals connected by the permission registry.

You should also prefer to use the attached methods when possible.
Those have some additional syntax aids, validation, and can take the user flags
and the global roles system into account.

#### `ObjectRole`

`ObjectRole` is an instantiation of a role definition for a particular object.
The `give_permission` method creates an object role if one does not exist for that (object, role definition)

##### `descendent_roles()`

For a given object role, if that role offers a "member_team" permission, this gives all
the roles that are implied by ownership of this role.

For object roles that do not offer that permission, or do not apply to a team
or a team's parent objects, this should return an empty set.

##### `needed_cache_updates()`

This shows the additions and removals needed to make the `RoleEvaluation` correct
for the particular `ObjectRole` in question.
This is used as a part of the re-computation logic to cache role-object-permission evaluations.

#### `RoleEvaluation`

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

##### `accessible_ids(cls, user, codename)`

Returns a queryset which is a values list of ids for objects of `cls` type
that `user` has the permission to, where that permission is given in `codename`.

This is lighter weight and more efficient than using `accessible_objects` when it is needed
as a subquery as a part of a larger query.

##### `accessible_objects(cls, user, codename)`

Return a queryset from `cls` model that `user` has the `codename` permission to.

##### `get_permissions(user, obj)`

Returns all permissions that `user` has to `obj`.
