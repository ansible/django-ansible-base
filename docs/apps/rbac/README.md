# Role-Based Access Control (RBAC)

As a feature of django-ansible-base, this provides access control for already-authenticated users.
Not having access for a specific request sent to the server usually results in a 403 permission denied response.

## DAB RBAC Documentation

The docs for the RBAC app are split according to the intended audience

### For Users

[Link to documentation for users](for_users.md)

These convey high-level definitions and concepts for the RBAC system.
This is necessarily vague, because this is only useful for someone using
the permissions system through a UI or something like that.
So this does not give specific locations for where roles or permissions
are managed, but tells what the expected outcome is from using the system.

### For API Clients

[Link to documentation for API clients](for_clients.md)

Since DAB RBAC vendors some endpoints itself, this outlines how to use those endpoints.

### For Django App Developers

[Link to documentation for Django app developers](for_app_developers.md)

This shows how to enable DAB RBAC in your Django project, register your models, etc.

### For DAB Developers

[Link to documentation for django-ansible-base (DAB) developers](for_dab_developers.md)

Internal docs for people working on DAB RBAC itself.
