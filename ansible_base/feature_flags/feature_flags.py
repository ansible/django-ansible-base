from typing import TypedDict


class AAPFlagNameSchema(TypedDict):
    name: str
    ui_name: str
    condition: str
    value: str
    required: str
    support_level: str
    visibility: str
    toggle_type: str
    description: str
    support_url: str
    labels: list


AAP_FEATURE_FLAGS: list[AAPFlagNameSchema] = [
    AAPFlagNameSchema(
        name="FEATURE_INDIRECT_NODE_COUNTING_ENABLED",
        ui_name="Indirect Node Counting",
        visibility="public",
        condition="boolean",
        value="False",
        support_level="NOT_FOR_PRODUCTION",
        description="TBD",
        support_url="https://docs.redhat.com/en/documentation/red_hat_ansible_automation_platform/2.5/",
        labels=['controller'],
    ),
    AAPFlagNameSchema(
        name="FEATURE_POLICY_AS_CODE_ENABLED",
        ui_name="Policy as Code",
        visibility="public",
        condition="boolean",
        value="False",
        support_level="NOT_FOR_PRODUCTION",
        description="TBD",
        support_url="https://docs.redhat.com/en/documentation/red_hat_ansible_automation_platform/2.5/",
        labels=['controller'],
    ),
    AAPFlagNameSchema(
        name="FEATURE_EDA_ANALYTICS_ENABLED",
        ui_name="Event-Driven Ansible Analytics",
        condition="boolean",
        value="False",
        visibility="public",
        support_level="NOT_FOR_PRODUCTION",
        description="TBD",
        support_url="https://docs.redhat.com/en/documentation/red_hat_ansible_automation_platform/2.5/",
        labels=['eda'],
    ),
    AAPFlagNameSchema(
        name="FEATURE_GATEWAY_IPV6_USAGE_ENABLED",
        ui_name="Gateway IPv6 Usage",
        condition="boolean",
        value="False",
        visibility="private",
        support_level="NOT_FOR_PRODUCTION",
        description="TBD",
        support_url="https://docs.redhat.com/en/documentation/red_hat_ansible_automation_platform/2.5/",
        labels=['gateway'],
    ),
    AAPFlagNameSchema(
        name="FEATURE_GATEWAY_CREATE_CRC_SERVICE_TYPE_ENABLED",
        ui_name="Gateway Create CRC Service Type",
        condition="boolean",
        value="False",
        visibility="private",
        support_level="NOT_FOR_PRODUCTION",
        description="TBD",
        support_url="https://docs.redhat.com/en/documentation/red_hat_ansible_automation_platform/2.5/",
        labels=['gateway'],
    ),
    AAPFlagNameSchema(
        name="FEATURE_DISPATCHERD_ENABLED",
        ui_name="AAP Dispatcherd",
        condition="boolean",
        value="False",
        visibility="private",
        support_level="NOT_FOR_PRODUCTION",
        description="TBD",
        support_url="https://docs.redhat.com/en/documentation/red_hat_ansible_automation_platform/2.5/",
        labels=['eda', 'controller'],
    ),
]
