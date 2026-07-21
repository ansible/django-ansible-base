# Deferred RBAC Computations

When creating or deleting many resources, the per-call RBAC signal handlers can
become a performance bottleneck. `defer_rbac_computations` batches all
signal-driven recomputation into a single flush pass on exit.

## `defer_rbac_computations` — resource create/delete

Use this context manager when creating or deleting many RBAC-registered objects
(e.g. bulk inventory creation, organization cascade delete). It defers the RBAC
signal handlers that normally fire on every `save()` and `delete()`, then
flushes all recomputation in a single pass when the context manager exits.

**This is only for non-RBAC resource operations.** It does not handle permission
assignments — use `RoleDefinition.bulk_give_permissions` /
`bulk_remove_permissions` for that (provided separately).

```python
from ansible_base.rbac.triggers import defer_rbac_computations

with defer_rbac_computations():
    for i in range(100):
        Inventory.objects.create(name=f'inv-{i}', organization=org)
# One recomputation pass here instead of 100
```

### What errors while active

Once resources have been created or deleted inside the context manager (i.e.
deferred data is pending), the following calls will raise `RuntimeError`:

- **`give_permission` / `remove_permission`** — these run incremental
  recomputation that would produce incorrect results against stale state.
- **`has_obj_perm`** — evaluations are stale until the flush completes, so
  permission checks would return wrong answers.

These calls are allowed *before* any mutations occur inside the context manager.
This means a view can enter `defer_rbac_computations()`, pass its DRF permission
checks normally, and then perform bulk resource operations.

### Constraints

- Cannot be nested.
- Only defers signals for resource create/delete — not for permission
  assignment.

### What it defers

- **Created resources:** defers `rbac_post_save_update_evaluations`, flushes
  parent ObjectRole lookups and `compute_object_role_permissions` once at exit.
- **Deleted resources:** defers `rbac_post_delete_remove_object_roles` and
  `team_pre_delete`, flushes bulk ObjectRole/RoleEvaluation cleanup at exit.
- **Team IDs:** collects all affected team IDs and calls
  `compute_team_member_roles` once.

## Migration from `defer_rbac_cache`

`defer_rbac_cache` has been removed. It was designed for the assignment path but
read stale `provides_teams` state when deferring, producing incorrect results.

| Old pattern | New pattern |
|---|---|
| `with defer_rbac_cache():` around `obj.delete()` | `with defer_rbac_computations():` |
| `with defer_rbac_cache():` around resource creation | `with defer_rbac_computations():` |
| `with defer_rbac_cache():` around `give_permission` calls | `RoleDefinition.bulk_give_permissions(...)` (separate API) |
