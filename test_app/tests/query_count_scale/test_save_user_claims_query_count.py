"""Query-count regression coverage for the save_user_claims code path.

Unlike the list-endpoint sweep, this measures the Python claims-processing path
directly. The path is called for JWT-authenticated requests and should not add a
query for every object-role grant.
"""

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext

from ansible_base.rbac.claims import (
    build_resource_cache,
    get_role_definition,
    save_user_claims,
)
from ansible_base.rbac.models import RoleUserAssignment
from test_app.models import Organization


def _organization_admin_claims(count: int) -> tuple[dict, dict]:
    organizations = list(Organization.objects.filter(name__startswith="large_organization_").order_by("id")[:count])
    assert len(organizations) == count, f"Expected {count} seeded organizations, got {len(organizations)}. " "The large query-count dataset may not be seeded."

    objects = {"organization": [], "team": []}
    object_roles = {
        "Organization Admin": {
            "content_type": "organization",
            "objects": list(range(count)),
        }
    }

    for organization in organizations:
        objects["organization"].append(
            {
                "ansible_id": str(organization.resource.ansible_id),
                "name": organization.name,
            }
        )

    return objects, object_roles


def test_save_user_claims_query_count_does_not_scale_with_grants(_seed_large_dataset):
    """A large claims payload should stay within a fixed query-count budget."""
    get_role_definition("Organization Admin")

    baseline_user = get_user_model().objects.get_or_create(username="save_user_claims_query_count_baseline")[0]
    baseline_objects, baseline_object_roles = _organization_admin_claims(1)
    with CaptureQueriesContext(connection) as baseline_queries:

        save_user_claims(
            baseline_user,
            objects=baseline_objects,
            object_roles=baseline_object_roles,
            global_roles=[],
        )

    user = get_user_model().objects.get_or_create(username="save_user_claims_query_count_user")[0]
    objects, object_roles = _organization_admin_claims(30)
    with CaptureQueriesContext(connection) as queries:
        save_user_claims(
            user,
            objects=objects,
            object_roles=object_roles,
            global_roles=[],
        )

    assignments = RoleUserAssignment.objects.filter(
        user=user,
        role_definition__name="Organization Admin",
        content_type__isnull=False,
    )
    assert assignments.count() == 30
    assert len(queries.captured_queries) <= len(baseline_queries.captured_queries) + 5, (
        "save_user_claims query count scaled with grants: "
        f"{len(baseline_queries.captured_queries)} queries for 1 grant versus "
        f"{len(queries.captured_queries)} queries for 30 grants."
    )


def test_resource_cache_resolves_objects_without_n_plus_one(_seed_large_dataset):
    """The resource cache should resolve Resource and content objects in bulk."""
    organizations = list(Organization.objects.filter(name__startswith="large_organization_").order_by("id")[:30])
    resource_keys = {(str(organization.resource.ansible_id), "organization") for organization in organizations}

    with CaptureQueriesContext(connection) as queries:
        resolved_resources = build_resource_cache(resource_keys)

    assert len(resolved_resources) == 30
    assert all(resource is not None and obj is not None for resource, obj in resolved_resources.values())
    assert len(queries.captured_queries) <= 3, (
        f"Resource cache used {len(queries.captured_queries)} queries for 30 " "organization resources; expected a small fixed count."
    )
