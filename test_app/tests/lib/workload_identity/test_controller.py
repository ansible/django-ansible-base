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
