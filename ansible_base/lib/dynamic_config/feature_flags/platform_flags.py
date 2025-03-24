from typing import TypedDict


class AAPFlagNameSchema(TypedDict):
    name: str
    condition: str
    value: str
    visibility: str
    support_level: str
    description: str
    labels: list
    toggle_type: str


AAP_FEATURE_FLAGS: list[AAPFlagNameSchema] = [
    AAPFlagNameSchema(
        name="FEATURE_FEATURE_FLAGS_ENABLED",
        condition="boolean",
        value="True",
        visibility="public",
        support_level='READY_FOR_PRODUCTION',
        description='If enabled, feature flags can be toggled on/off at runtime via UI or API. '
        'If disabled, feature flags can only be toggled on/off at install-time.',
        labels=['platform'],
        toggle_type='install-time',
    ),
    AAPFlagNameSchema(
        name="FEATURE_INDIRECT_NODE_COUNTING_ENABLED",
        visibility="public",
        condition="boolean",
        value="False",
        support_level="NOT_FOR_PRODUCTION",
        description="TBD",
        labels=['controller'],
    ),
    AAPFlagNameSchema(
        name="FEATURE_POLICY_AS_CODE_ENABLED",
        visibility="public",
        condition="boolean",
        value="False",
        support_level="NOT_FOR_PRODUCTION",
        description="TBD",
        labels=['controller'],
    ),
    AAPFlagNameSchema(
        name="FEATURE_EDA_ANALYTICS_ENABLED",
        condition="boolean",
        value="False",
        visibility="public",
        support_level="NOT_FOR_PRODUCTION",
        description="TBD",
        labels=['eda'],
    ),
]
