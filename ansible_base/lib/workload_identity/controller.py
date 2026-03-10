"""
OIDC Workload Identity Scope for AAP Controller.

Defines the scope and claims for Controller automation job workload identity.
"""

from .base import BaseWorkloadIdentityScope


class AutomationControllerJobScope(BaseWorkloadIdentityScope):
    """
    Default scope for AAP Controller automation job workload identity.

    Note: populate_claims() is not yet implemented and will be added
    in a future iteration.
    """

    name = "aap_controller_automation_job"
    description = "Default AAP Controller automation job workload identity"

    CLAIM_JOB_ID = 'aap_controller_job_id'
    CLAIM_JOB_NAME = 'aap_controller_job_name'
    CLAIM_JOB_TYPE = 'aap_controller_job_type'
    CLAIM_LAUNCH_TYPE = 'aap_controller_launch_type'
    CLAIM_PLAYBOOK_NAME = 'aap_controller_playbook_name'
    CLAIM_LAUNCHED_BY_NAME = 'aap_controller_launched_by_name'
    CLAIM_LAUNCHED_BY_ID = 'aap_controller_launched_by_id'
    CLAIM_ORGANIZATION_NAME = 'aap_controller_organization_name'
    CLAIM_ORGANIZATION_ID = 'aap_controller_organization_id'
    CLAIM_INVENTORY_NAME = 'aap_controller_inventory_name'
    CLAIM_INVENTORY_ID = 'aap_controller_inventory_id'
    CLAIM_EXECUTION_ENVIRONMENT_NAME = 'aap_controller_execution_environment_name'
    CLAIM_EXECUTION_ENVIRONMENT_ID = 'aap_controller_execution_environment_id'
    CLAIM_PROJECT_NAME = 'aap_controller_project_name'
    CLAIM_PROJECT_ID = 'aap_controller_project_id'
    CLAIM_JOB_TEMPLATE_NAME = 'aap_controller_job_template_name'
    CLAIM_JOB_TEMPLATE_ID = 'aap_controller_job_template_id'
    CLAIM_UNIFIED_JOB_TEMPLATE_NAME = 'aap_controller_unified_job_template_name'
    CLAIM_UNIFIED_JOB_TEMPLATE_ID = 'aap_controller_unified_job_template_id'
    CLAIM_INSTANCE_GROUP_NAME = 'aap_controller_instance_group_name'
    CLAIM_INSTANCE_GROUP_ID = 'aap_controller_instance_group_id'

    @classmethod
    def list_claims(cls) -> list[str]:
        return [getattr(cls, attr) for attr in dir(cls) if attr.startswith('CLAIM_')]

    @classmethod
    def get_target_claim_names_to_sub_stubs(cls) -> dict[str, str]:
        return {
            cls.CLAIM_ORGANIZATION_NAME: "organization",
            cls.CLAIM_JOB_TEMPLATE_NAME: "job_template",
        }
