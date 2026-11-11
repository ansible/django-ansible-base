"""Regression tests: bulk RBAC paths must stay under the SQL Server parameter limit.

SQL Server caps a single query at 2100 bound parameters. mssql-django routes
plain ``__in`` lookups through a temp table, but OR-ed Q pairs, Case/When
UPDATE entries, and other inline-bound constructs count every value against
the limit. These tests wrap every executed query and assert the cap holds.
"""

from collections import namedtuple
from types import SimpleNamespace

import pytest
from django.db import connection

from ansible_base.lib.mssql.params import SQL_SERVER_MAX_QUERY_PARAMETERS
from ansible_base.rbac import permission_registry


def _assert_sql_server_parameter_limit(parameter_counts):
    def execute_with_parameter_limit(execute, sql, params, many, context):
        parameter_count = len(params or ())
        parameter_counts.append(parameter_count)
        assert parameter_count <= SQL_SERVER_MAX_QUERY_PARAMETERS, f"Query used {parameter_count} parameters: {sql[:200]}"
        return execute(sql, params, many, context)

    return execute_with_parameter_limit


OVER_LIMIT_COUNT = SQL_SERVER_MAX_QUERY_PARAMETERS + 1  # one more than the hard ceiling


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor != 'microsoft', reason='SQL Server parameter limit regression test')
def test_deferred_role_cleanup_large_object_id_sets_stay_under_parameter_limit():
    from ansible_base.rbac.caching import cleanup_deleted_object_roles, cleanup_deleted_team_roles

    object_ids = set(range(100000, 100000 + OVER_LIMIT_COUNT))
    object_pks = [(permission_registry.team_ct_id, object_id) for object_id in object_ids]

    parameter_counts = []
    with connection.execute_wrapper(_assert_sql_server_parameter_limit(parameter_counts)):
        ancestor_roles, deleted_team_role_ids = cleanup_deleted_team_roles(object_ids)
        deleted_object_role_ids = cleanup_deleted_object_roles(object_pks)

    assert parameter_counts
    assert max(parameter_counts) <= SQL_SERVER_MAX_QUERY_PARAMETERS
    assert not ancestor_roles
    assert not deleted_team_role_ids
    assert not deleted_object_role_ids


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor != 'microsoft', reason='SQL Server parameter limit regression test')
def test_object_roles_for_parents_large_parent_sets_stay_under_parameter_limit():
    from ansible_base.rbac.caching import object_roles_for_parents

    Parent = namedtuple('Parent', ['content_type_id', 'pk'])
    parents = {Parent(content_type_id=permission_registry.team_ct_id, pk=object_id) for object_id in range(OVER_LIMIT_COUNT)}

    parameter_counts = []
    with connection.execute_wrapper(_assert_sql_server_parameter_limit(parameter_counts)):
        roles = object_roles_for_parents(parents)

    assert parameter_counts
    assert max(parameter_counts) <= SQL_SERVER_MAX_QUERY_PARAMETERS
    assert not roles


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor != 'microsoft', reason='SQL Server parameter limit regression test')
def test_update_assignment_resource_ids_large_sets_stay_under_parameter_limit(organization):
    from ansible_base.resource_registry.apps import _update_assignment_resource_ids

    content_type = permission_registry.content_type_model.objects.get_for_model(type(organization))
    resource_ids = {str(object_id): f'00000000-0000-0000-0000-{object_id:012d}' for object_id in range(OVER_LIMIT_COUNT)}

    parameter_counts = []
    with connection.execute_wrapper(_assert_sql_server_parameter_limit(parameter_counts)):
        _update_assignment_resource_ids(content_type, resource_ids)

    assert parameter_counts
    assert max(parameter_counts) <= SQL_SERVER_MAX_QUERY_PARAMETERS


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor != 'microsoft', reason='SQL Server parameter limit regression test')
def test_find_assignments_large_batches_stay_under_parameter_limit(rando, inv_rd):
    from ansible_base.rbac.models import RoleUserAssignment
    from ansible_base.rbac.pipeline import ResolvedAssignment, _find_assignments
    from test_app.models import Inventory

    content_type = permission_registry.content_type_model.objects.get_for_model(Inventory)
    resolved = [
        ResolvedAssignment(
            role_definition=inv_rd,
            actor=rando,
            content_type=content_type,
            object_id=str(object_id),
            parent_reference='',
        )
        for object_id in range(OVER_LIMIT_COUNT)
    ]
    lookup = {(inv_rd.pk, str(object_id)): SimpleNamespace(pk=object_id) for object_id in range(OVER_LIMIT_COUNT)}

    parameter_counts = []
    with connection.execute_wrapper(_assert_sql_server_parameter_limit(parameter_counts)):
        assignments = _find_assignments(resolved, lookup, RoleUserAssignment, 'user_id')

    assert parameter_counts
    assert max(parameter_counts) <= SQL_SERVER_MAX_QUERY_PARAMETERS
    assert assignments == []
