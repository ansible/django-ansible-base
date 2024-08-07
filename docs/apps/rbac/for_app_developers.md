## Using DAB RBAC in a Django Project

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

#### Post-migrate Actions

The DAB RBAC app will create permission entries in a `post_migrate` signal.
This is expected to run _after_ any post_migrate signals from _your_ app,
because "ansible_base.rbac" needs to come later in `INSTALLED_APPS`.

Because of this, DAB RBAC sends a special signal so you can run logic after
permissions are created.

```python
from ansible_base.rbac.triggers import dab_post_migrate

dab_post_migrate.connect(my_logic, dispatch_uid="my_logic")
```

By doing this, you can write code in `my_logic` that references `DABPermission`
entries. This would be a common place to create managed RoleDefinitions, for example.

This will still rebuild the role evaluation entries afterwards.
This is so that DAB RBAC will be in a consistent state after any logic you run.

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

    def filter_queryset(self, queryset):
        return super().filter_queryset(MyModel.access_qs(self.request.user, queryset=queryset))  # (3)
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
from ansible_base.rbac.models import RoleDefinition

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
from ansible_base.rbac.permission_registry import permission_registry

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
- filter existing `queryset` to objects user can view `MyModel.access_qs(user, queryset)`
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

#### Models Without View Permission

Your model's `Meta` can exclude the "view" permission by not listing it in
the `default_permissions` property.
These cases are considered "public" models, and methods like `MyModel.access_qs(user)`
will return a queryset that include _all_ objects, regardless of the `user` passed in.
However, the "view_mymodel" permission is still considered invalid if passed into
an evaluation method, because that permission does not exist.

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

### RBAC vs User Flag Responsibilities

With some user flags, like the standard `is_superuser` flag, the RBAC system does not
need to be consulted to make an evaluation.
You may or may not want this to be done as part of the attached methods
like `access_qs` or `has_obj_perm`. That can be controlled with these.

```
ANSIBLE_BASE_BYPASS_SUPERUSER_FLAGS = ['is_superuser']
ANSIBLE_BASE_BYPASS_ACTION_FLAGS = {'view': 'is_platform_auditor'}
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
permission_registry.track_relationship(Team, 'users', 'Team Member')
permission_registry.track_relationship(Team, 'team_parents', 'Team Member')
```

This only works with our 2 "actor" types of users and teams.
Adding these lines will synchronize users and teams of team-object-roles with the "team-member"
role definition (by name) to the `Team.users`
and `Team.tracked_parents` ManyToMany relationships, respectively.
So if you have a team object, `team.users.add(user)` will also give that
user _member permission_ to that team, where those permissions are defined by the
role definition with the name "team-member".


### Role assignment callback

Apps that utilize django-ansible-base may wish to add extra validation when assigning roles to actors (users or teams).

see [Validation callback for role assignment](../../lib/validation.md)
