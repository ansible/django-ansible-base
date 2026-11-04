# Adding Organization-Scoped "Automation Dashboard" Permissions

This guide describes how to add two new permissions that are scoped to an
organization — an **Automation Dashboard Viewer** permission and an **Automation
Dashboard Editor** permission — and expose them as organization-scoped roles.

It is based on the POC branch `poc/automation-dashboard-org-permissions`, which
implements and tests the complete recipe in `test_app`:

| POC file | Purpose |
|---|---|
| `test_app/models.py` (`Organization.Meta.permissions`) | declares the permission codenames |
| `test_app/migrations/0020_automation_dashboard_organization_permissions.py` | alters model options and creates the role definitions |
| `test_app/tests/rbac/test_automation_dashboard_org_permissions.py` | verifies permissions, roles, and access |

> **Important:** `django-ansible-base` has no automation-dashboard code of its
> own. The names below are examples; consumers (for example AWX) own the model
> and the feature. The mechanics are identical for any consumer app.

---

## 1. Understand the two layers

DAB RBAC separates **permissions** from **roles**:

1. **Permissions** are codenames attached to a model's content type. They come
   from the model's `Meta.default_permissions` and `Meta.permissions` and are
   copied into `dab_rbac.DABPermission` by the `post_migrate` hook in
   `ansible_base/rbac/management/__init__.py` (`sync_dab_permissions`).
2. **Roles** (`dab_rbac.RoleDefinition`) group permissions and have a
   `content_type`. A role whose `content_type` is the organization model can be
   assigned on a specific organization; that is what makes the permission
   organization-scoped.

A permission alone does not let anyone do anything — you must also create a
`RoleDefinition` containing it and assign that role to users/teams on an
organization.

---

## 2. Declare the permissions on the organization model

Add the codenames to the organization model's `Meta.permissions`. In the POC
this is `test_app/models.py`:

```python
class Organization(AbstractOrganization):
    class Meta:
        ordering = ['id']
        permissions = [
            ('member_organization', 'User is member of this organization'),
            ('view_automation_dashboard_organization',
             'Can view the automation dashboard for this organization'),
            ('change_automation_dashboard_organization',
             'Can edit the automation dashboard for this organization'),
        ]
```

For a real consumer, the equivalent is AWX's
`awx/main/models/organization.py` (see the existing `member_organization` and
`audit_organization` entries).

Naming rules:

- Use `{action}_{target}`. Keep the `_organization` suffix so it is clear the
  permission lives on the organization content type.
- Codenames must be **unique across all RBAC-registered models**; a duplicate
  codename on another registered model is rejected
  (`docs/apps/rbac/for_app_developers.md`).
- Make sure the organization model is registered with the permission registry.
  In `test_app`: `test_app/models.py`
  (`permission_registry.register(Organization, ...)`); in AWX:
  `awx/main/models/__init__.py`. Permission sync only covers registered models.

---

## 3. Create the Django migration

Generate the migration with `makemigrations`; it will be an
`AlterModelOptions` operation. The POC migration is:

```python
migrations.AlterModelOptions(
    name='organization',
    options={
        'ordering': ['id'],
        'permissions': [
            ('member_organization', 'User is member of this organization'),
            ('view_automation_dashboard_organization', '...'),
            ('change_automation_dashboard_organization', '...'),
        ],
    },
),
```

Verify it is complete:

```bash
DJANGO_SETTINGS_MODULE=test_app.sqlite3settings .venv/bin/python manage.py makemigrations --check --dry-run
# Expected: No changes detected
```

---

## 4. Create the organization-scoped role definitions

Create two `RoleDefinition`s whose `content_type` is the **organization** content
type. Omitting `content_type` produces a system-wide role instead, which is the
most common mistake.

Recommended permission sets:

- **Automation Dashboard Viewer**: `view_organization` +
  `view_automation_dashboard_organization`
- **Automation Dashboard Editor**: the viewer permissions +
  `change_automation_dashboard_organization`

`view_organization` is included in both because DAB requires roles that contain a
non-view codename to also contain a view codename for the same model
(`ANSIBLE_BASE_ROLES_REQUIRE_VIEW`, default `True`; see
`ansible_base/rbac/validators.py:check_view_permission_criteria`). It also lets
the UI render the organization to a delegated user.

### Production path: data migration

Create the roles in a `RunPython` migration. The POC uses:

```python
def create_automation_dashboard_roles(apps, schema_editor):
    # DAB normally creates DABPermission rows in post_migrate, which has NOT run
    # yet inside a migration. Materialize them first.
    create_dab_permissions(global_apps.get_app_config('dab_rbac'), apps=apps)

    DABContentType = apps.get_model('dab_rbac', 'DABContentType')
    DABPermission = apps.get_model('dab_rbac', 'DABPermission')
    RoleDefinition = apps.get_model('dab_rbac', 'RoleDefinition')
    Organization = apps.get_model(settings.ANSIBLE_BASE_ORGANIZATION_MODEL)

    org_ct = DABContentType.objects.get_for_model(Organization)

    def perm(codename):
        return DABPermission.objects.get(content_type=org_ct, codename=codename)

    viewer_permissions = [
        perm('view_organization'),
        perm('view_automation_dashboard_organization'),
    ]
    editor_permissions = viewer_permissions + [
        perm('change_automation_dashboard_organization'),
    ]

    for name, description, permissions in (
        ('Automation Dashboard Viewer', 'Can view the automation dashboard for a single organization', viewer_permissions),
        ('Automation Dashboard Editor', 'Can view and edit the automation dashboard for a single organization', editor_permissions),
    ):
        rd, _ = RoleDefinition.objects.get_or_create(
            name=name,
            defaults={'description': description, 'content_type': org_ct, 'managed': True},
        )
        rd.permissions.set(permissions)
```

Key points:

- **Timing gotcha:** DAB's permission sync runs in `post_migrate`, after all
  migrations. A migration that references `DABPermission` by codename must call
  `create_dab_permissions(global_apps.get_app_config('dab_rbac'), apps=apps)`
  itself. AWX does the same in `awx/main/migrations/_dab_rbac.py`
  (`create_permissions_as_operation`).
- Use the historical models from the `apps` registry inside migrations.
- Make the migration idempotent (`get_or_create` + `permissions.set`).
- Set `managed=True` for roles the system owns. AWX's
  `setup_managed_role_definitions` also prunes managed roles it no longer owns;
  replicate that if you need exact-managed-set semantics.
- Add `('dab_rbac', '__first__')` to the migration's dependencies.

### Alternative: runtime / settings-based creation

Outside migrations you can use the public manager, which validates the
permission set:

```python
from ansible_base.rbac.models import RoleDefinition
from ansible_base.rbac.permission_registry import permission_registry
from django.conf import settings

Organization = permission_registry.apps.get_model(settings.ANSIBLE_BASE_ORGANIZATION_MODEL)
org_ct = permission_registry.content_type_model.objects.get_for_model(Organization)

RoleDefinition.objects.get_or_create(
    name='Automation Dashboard Viewer',
    content_type=org_ct,
    managed=True,
    permissions=['view_organization', 'view_automation_dashboard_organization'],
)
```

You can also register reusable managed roles in
`ANSIBLE_BASE_MANAGED_ROLE_REGISTRY` using the `ManagedAdminBase` /
`ManagedActionBase` templates from `ansible_base/rbac/managed.py` (see
`test_app/defaults.py` for an example). Those templates grant a whole class of
permissions (or one action plus `view`); for this feature the explicit
permission list above is clearer.

---

## 5. Enforce the permission

Use the standard DAB helpers in the consumer's access layer:

```python
# list filtering
Organization.access_qs(user, 'view_automation_dashboard_organization')

# object-level check
user.has_obj_perm(organization, 'change_automation_dashboard_organization')
```

For DRF views, `AnsibleBaseObjectPermissions` will check
`<rbac_action>_<model>` when the view defines `rbac_action`
(`ansible_base/rbac/api/permissions.py`). The `/role-definitions/` and
`/role-user-assignments/` APIs automatically surface the new permissions once
the `DABPermission` rows exist — no extra registration is needed.

---

## 6. Test

The POC tests verify:

1. Both `DABPermission` rows exist with the organization content type.
2. Both role definitions exist, are `managed`, have the organization content
   type, and contain the expected permission sets.
3. A user assigned the viewer role can view but not change; a user assigned the
   editor role can both view and change.
4. `Organization.access_qs(...)` reflects the grants.

Run them with SQLite if you do not have the Postgres test database available:

```bash
DJANGO_SETTINGS_MODULE=test_app.sqlite3settings \
  .venv/bin/python -m pytest \
  test_app/tests/rbac/test_automation_dashboard_org_permissions.py
```

---

## 7. Checklist / common omissions

- [ ] Permission codenames added to the **organization** model's
      `Meta.permissions` (not a child model's).
- [ ] `AlterModelOptions` migration generated and `makemigrations --check`
      passes.
- [ ] Organization model is registered in the permission registry.
- [ ] Any data migration that references permissions calls
      `create_dab_permissions(...)` first — `post_migrate` has not run yet.
- [ ] Role definitions have `content_type=<organization content type>`; omitting
      it creates system-wide roles.
- [ ] Editor role includes a view permission (`view_organization` and/or
      `view_automation_dashboard_organization`) to satisfy
      `ANSIBLE_BASE_ROLES_REQUIRE_VIEW`.
- [ ] Role definitions are idempotent and marked `managed=True` if the system
      owns them.
- [ ] Permission checks (`access_qs` / `has_obj_perm`) and UI role labels are
      updated in the consumer.
- [ ] Tests cover permission creation, role creation, assignment, and access
      filtering.

---

## 8. If the dashboard is a separate model

If "Automation Dashboard" becomes its own model rather than permissions on the
organization itself:

1. Declare `view_automationdashboard` / `change_automationdashboard` on that
   model's `Meta` (or rely on default view/change permissions).
2. Register it with the parent relationship:
   `permission_registry.register(AutomationDashboard, parent_field_name='organization')`,
   or add it to `ANSIBLE_BASE_RBAC_MODEL_REGISTRY`.
3. Its permissions then become valid in organization-scoped role definitions
   automatically, because `permissions_allowed_for_role(Organization)` includes
   descendant models (`ansible_base/rbac/validators.py`).
4. The role definitions still use `content_type=<organization content type>`
   when the roles are assigned on organizations.
