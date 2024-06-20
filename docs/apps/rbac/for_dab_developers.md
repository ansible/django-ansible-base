## DAB RBAC System Design Principles

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
