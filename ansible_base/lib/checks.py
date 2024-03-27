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

import django.apps
from django.core.checks import Error, register
from django.db import models


@register()
def check_charfield_has_max_length(app_configs, **kwargs):
    errors = []
    for model in django.apps.apps.get_models():
        for field in model._meta.fields:
            if isinstance(field, models.CharField) and field.max_length is None:
                errors.append(
                    Error(
                        'CharField must have a max_length',
                        hint=f"Add max_length parameter for field '{field.name}' in {model.__name__}",
                        id='ansible_base.E001',
                    )
                )
    return errors
