#  Copyright 2024 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

TRIGGER_DEFINITION = {
    # If adding a top level change create_claims in common.py
    "always": {
        "type": {},
        "keys": {},
    },
    "never": {"type": {}, "keys": {}},
    "groups": {
        "type": {},
        "keys": {
            # If adding a group key be sure to modify process_groups in common.py
            "has_or": {
                "type": [],
                "contents": "",
            },
            "has_and": {
                "type": [],
                "contents": "",
            },
            "has_not": {
                "type": [],
                "contents": "",
            },
        },
    },
    "attributes": {
        "type": {},
        "keys": {
            # If adding a key or */keys be sure to modify process_user_attributes in common.py
            "join_condition": {
                "type": "",
                "choices": ["or", "and"],
            },
            "*": {
                "type": {},
                "keys": {
                    "contains": {
                        "type": "",
                    },
                    "matches": {
                        "type": "",
                    },
                    "ends_with": {
                        "type": "",
                    },
                    "equals": {
                        "type": "",
                    },
                    "in": {
                        "type": [],
                        "contents": "",
                    },
                },
            },
        },
    },
}
