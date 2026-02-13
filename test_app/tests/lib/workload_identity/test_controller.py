import pytest

from ansible_base.lib.workload_identity.controller import AutomationControllerJobScope


def test_list_claims():
    """
    Test that AutomationControllerJobScope defines the correct set of claims.
    """
    expected_claims = {
        'aap_controller_job_id',
        'aap_controller_job_name',
        'aap_controller_job_type',
        'aap_controller_launch_type',
        'aap_controller_playbook_name',
        'aap_controller_launched_by_name',
        'aap_controller_launched_by_id',
        'aap_controller_organization_name',
        'aap_controller_organization_id',
        'aap_controller_inventory_name',
        'aap_controller_inventory_id',
        'aap_controller_execution_environment_name',
        'aap_controller_execution_environment_id',
        'aap_controller_project_name',
        'aap_controller_project_id',
        'aap_controller_job_template_name',
        'aap_controller_job_template_id',
        'aap_controller_unified_job_template_name',
        'aap_controller_unified_job_template_id',
        'aap_controller_instance_group_name',
        'aap_controller_instance_group_id',
    }

    scope = AutomationControllerJobScope()
    actual_claims = set(scope.list_claims())

    assert actual_claims == expected_claims


def test_get_target_claim_names_to_sub_stubs():
    """
    Test that get_target_claim_names_to_sub_stubs returns the correct mapping
    of claim names to their sub claim stubs.
    """
    expected_mapping = {
        'aap_controller_job_name': 'job',
        'aap_controller_organization_name': 'organization',
        'aap_controller_project_name': 'project',
        'aap_controller_job_template_name': 'job_template',
    }

    actual_mapping = AutomationControllerJobScope.get_target_claim_names_to_sub_stubs()

    assert actual_mapping == expected_mapping


def test_get_target_claim_names_to_sub_stubs_keys_are_valid_claims():
    """
    Test that all keys in the target claim names mapping are valid claims
    defined in the scope.
    """
    mapping = AutomationControllerJobScope.get_target_claim_names_to_sub_stubs()
    all_claims = set(AutomationControllerJobScope.list_claims())

    for claim_name in mapping.keys():
        assert claim_name in all_claims, f"{claim_name} is not a valid claim in AutomationControllerJobScope"


@pytest.mark.parametrize(
    "workload_claims,expected_sub_claim",
    [
        (
            {
                'aap_controller_job_name': 'my-job',
                'aap_controller_organization_name': 'my-org',
                'aap_controller_project_name': 'my-project',
                'aap_controller_job_template_name': 'my-template',
            },
            "job:my-job:organization:my-org:project:my-project:job_template:my-template",
        ),
        (
            {
                'aap_controller_job_name': 'my-job',
                'aap_controller_organization_name': '',
                'aap_controller_project_name': 'my-project',
                'aap_controller_job_template_name': '',
            },
            "job:my-job:organization::project:my-project:job_template:",
        ),
        (
            {
                'aap_controller_job_name': 'my-job',
                'aap_controller_project_name': 'my-project',
            },
            "job:my-job:organization::project:my-project:job_template:",
        ),
    ],
)
def test_generate_sub_claim(workload_claims, expected_sub_claim):
    """
    Test that generate_sub_claim produces the correct sub claim string
    with full values, empty values, and missing keys.
    """
    actual_sub_claim = AutomationControllerJobScope.generate_sub_claim(workload_claims)
    assert actual_sub_claim == expected_sub_claim
