# Bulk RBAC Operations

## Deferred RBAC Computations

When creating or deleting many resources, the per-call RBAC signal handlers can
become a performance bottleneck. `defer_rbac_computations` batches all
signal-driven recomputation into a single flush pass on exit.

### `defer_rbac_computations` — resource create/delete

Use this context manager when creating or deleting many RBAC-registered objects
(e.g. bulk inventory creation, organization cascade delete). It defers the RBAC
signal handlers that normally fire on every `save()` and `delete()`, then
flushes all recomputation in a single pass when the context manager exits.

```python
from ansible_base.rbac.triggers import defer_rbac_computations

with defer_rbac_computations():
    for i in range(100):
        Inventory.objects.create(name=f'inv-{i}', organization=org)
# One recomputation pass here instead of 100
```

#### What errors while active

Once resources have been created or deleted inside the context manager (i.e.
deferred data is pending), the following calls will raise `RuntimeError`:

- **`has_obj_perm`** — evaluations are stale until the flush completes, so
  permission checks would return wrong answers.

`give_permission` / `remove_permission` delegate to the bulk functions and work
correctly inside this context manager.

#### Constraints

- Cannot be nested.
- Only defers signals for resource create/delete — not for permission
  assignment.

#### What it defers

- **Created resources:** defers `rbac_post_save_update_evaluations`, flushes
  parent ObjectRole lookups and `compute_object_role_permissions` once at exit.
- **Deleted resources:** defers `rbac_post_delete_remove_object_roles` and
  `team_pre_delete`, flushes bulk ObjectRole/RoleEvaluation cleanup at exit.
- **Team IDs:** collects all affected team IDs and calls
  `compute_team_member_roles` once.

### Migration from `defer_rbac_cache`

`defer_rbac_cache` has been removed. It was designed for the assignment path but
read stale `provides_teams` state when deferring, producing incorrect results.

| Old pattern | New pattern |
|---|---|
| `with defer_rbac_cache():` around `obj.delete()` | `with defer_rbac_computations():` |
| `with defer_rbac_cache():` around resource creation | `with defer_rbac_computations():` |
| `with defer_rbac_cache():` around `give_permission` calls | `bulk_give_permissions(...)` (separate API) |

## Bulk Permission Assignment

When assigning or removing permissions across many role definitions, users,
teams, and objects, looping over individual `give_permission` /
`remove_permission` calls is a performance bottleneck. DAB provides bulk
functions that batch the work into a single recomputation pass.

### `bulk_give_permissions` — permission assignment

Use this function when assigning permissions across multiple role definitions,
users, teams, and objects. It replaces looping over `give_permission` calls.

```python
from ansible_base.rbac.bulk import bulk_give_permissions

bulk_give_permissions(
    user_permissions=[
        (member_rd, user1, team_a),
        (member_rd, user2, team_a),
        (org_admin_rd, user1, org),
        (inv_admin_rd, user3, inv1),
    ],
    team_permissions=[
        (inv_admin_rd, team_a, inv1),
        (inv_admin_rd, team_a, inv2),
    ],
)
```

Each entry is a `(role_definition, actor, content_object)` triple. User and team
permissions are separated because team assignments trigger additional
recomputation (ancestor roles, `provides_teams`, descendent roles).

#### What it does

1. Validates once per unique `(role_definition, content_type)` pair
2. Bulk-creates ObjectRoles with `ignore_conflicts`
3. Bulk-creates `RoleUserAssignment` / `RoleTeamAssignment` with `ignore_conflicts`
4. Runs a single `compute_team_member_roles` + `compute_object_role_permissions` pass

#### Constraints

- Idempotent — calling with the same triples twice will not duplicate assignments.

### `bulk_remove_permissions` — permission removal

Same API shape as `bulk_give_permissions`, but for removal:

```python
from ansible_base.rbac.bulk import bulk_remove_permissions

bulk_remove_permissions(
    user_permissions=[
        (member_rd, user1, team_a),
        (inv_admin_rd, user3, inv1),
    ],
)
```

Bulk-deletes assignments, cleans up orphaned ObjectRoles, and runs a single
recomputation pass. Same constraints as `bulk_give_permissions`.

### When to use bulk methods vs `defer_rbac_computations`

These APIs handle different concerns:

| Scenario | Use |
|---|---|
| Bulk permission assignment/removal | `bulk_give_permissions(...)` / `bulk_remove_permissions(...)` |
| Bulk resource creation/deletion (e.g. org delete cascade) | `defer_rbac_computations` context manager |
