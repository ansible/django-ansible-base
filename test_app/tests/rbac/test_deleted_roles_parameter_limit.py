import pytest
from django.db import connection

from ansible_base.lib.utils.mssql import SQL_SERVER_MAX_QUERY_PARAMETERS
from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import ObjectRole


def _assert_sql_server_parameter_limit(parameter_counts):
    def execute_with_parameter_limit(execute, sql, params, many, context):
        parameter_count = len(params or ())
        parameter_counts.append(parameter_count)
        assert parameter_count <= SQL_SERVER_MAX_QUERY_PARAMETERS, f"Query used {parameter_count} parameters: {sql[:200]}"
        return execute(sql, params, many, context)

    return execute_with_parameter_limit


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor != 'microsoft', reason='SQL Server parameter limit regression test')
def test_delete_object_roles_large_candidate_sets_stay_under_parameter_limit(inv_rd):
    from ansible_base.rbac.caching import delete_object_roles

    object_role_count = 2101
    content_type = inv_rd.content_type
    ObjectRole.objects.bulk_create(
        [ObjectRole(role_definition=inv_rd, content_type=content_type, object_id=f'parameter-limit-{index}') for index in range(object_role_count)],
        batch_size=200,
    )

    parameter_counts = []
    with connection.execute_wrapper(_assert_sql_server_parameter_limit(parameter_counts)):
        deleted_count, _ = delete_object_roles(ObjectRole.objects.filter(role_definition=inv_rd))

    assert parameter_counts
    assert deleted_count >= object_role_count
    assert not ObjectRole.objects.filter(role_definition=inv_rd).exists()


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor != 'microsoft', reason='SQL Server parameter limit regression test')
def test_deferred_role_cleanup_large_object_id_sets_stay_under_parameter_limit():
    from ansible_base.rbac.caching import cleanup_deleted_object_roles, cleanup_deleted_team_roles

    object_ids = set(range(100000, 102101))
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
