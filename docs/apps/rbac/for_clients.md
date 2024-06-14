## Using DAB RBAC as an API Client

This section tells how to use the API endpoints as a client;
what requests to make and how to build request data.

You need a server running a Django project that uses this system.
Use test_app in this repo for a demo, see `test_app/README.md` for bootstrap.
http://127.0.0.1:8000/admin/ allows login as admin user (password is "password").

### Create Custom Role (Definition)

After logging in to test_app/, you can visit this endpoint to get the role definition API.

http://127.0.0.1:8000/api/v1/role_definitions/

Perform an OPTIONS request, and you will find this gives choices for `content_type`.
Out of the choices a single `content_type` needs to be chosen for a role definition.

Multiple permissions can be selected, and are accepted in the form of a list.
To find out what permissions are valid for a role definition for a given `content_type`
make a GET to `/api/v1/role_metadata/` and look up the type under "allowed_permissions".

A POST to this endpoint will create a new role definition, example data:

```json
{
    "permissions": ["view_inventory"],
    "content_type": "aap.inventory",
    "name": "View a single inventory",
    "description": "custom role"
}
```

Name can be any string that's not blank. Description can be any string.

### Assigning a User a Role to an Object

Select a role definition from `/api/v1/role_definitions/`, use the id as `role_definition`
and a user from `/api/v1/users/` and use the id as `user`.
Given the type of the role definition, check the available objects of that type,
in this case `/api/v1/inventories/` and obtain the desired id, this will become `object_id`.

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
