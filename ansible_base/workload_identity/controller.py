"""
OIDC Workload Identity Scope for AAP Controller.

Defines the scope and claims for Controller automation job workload identity.
"""

from ansible_base.workload_identity.base import BaseWorkloadIdentityScope


class AutomationControllerJobScope(BaseWorkloadIdentityScope):
    """
    Default scope for AAP Controller automation job workload identity.
    """

    name = "aap_controller_automation_job"
    description = "Default AAP Controller automation job workload identity"

    CLAIM_JOB_ID = 'aap_controller_job_id'
    CLAIM_JOB_NAME = 'aap_controller_job_name'
    CLAIM_JOB_TYPE = 'aap_controller_job_type'
    CLAIM_LAUNCH_TYPE = 'aap_controller_launch_type'
    CLAIM_PLAYBOOK_NAME = 'aap_controller_playbook_name'
    CLAIM_LAUNCHED_BY_USER_NAME = 'aap_controller_launched_by_user_name'
    CLAIM_LAUNCHED_BY_USER_ID = 'aap_controller_launched_by_user_id'
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

    def list_claims(self) -> list[str]:
        return [
            self.CLAIM_JOB_ID,
            self.CLAIM_JOB_NAME,
            self.CLAIM_JOB_TYPE,
            self.CLAIM_LAUNCH_TYPE,
            self.CLAIM_PLAYBOOK_NAME,
            self.CLAIM_LAUNCHED_BY_USER_NAME,
            self.CLAIM_LAUNCHED_BY_USER_ID,
            self.CLAIM_ORGANIZATION_NAME,
            self.CLAIM_ORGANIZATION_ID,
            self.CLAIM_INVENTORY_NAME,
            self.CLAIM_INVENTORY_ID,
            self.CLAIM_EXECUTION_ENVIRONMENT_NAME,
            self.CLAIM_EXECUTION_ENVIRONMENT_ID,
            self.CLAIM_PROJECT_NAME,
            self.CLAIM_PROJECT_ID,
            self.CLAIM_JOB_TEMPLATE_NAME,
            self.CLAIM_JOB_TEMPLATE_ID,
            self.CLAIM_UNIFIED_JOB_TEMPLATE_NAME,
            self.CLAIM_UNIFIED_JOB_TEMPLATE_ID,
            self.CLAIM_INSTANCE_GROUP_NAME,
            self.CLAIM_INSTANCE_GROUP_ID,
        ]
