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

from django.contrib import admin

from ansible_base.lib.admin import ReadOnlyAdmin
from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleEvaluation, RoleTeamAssignment, RoleUserAssignment

admin.site.register(RoleDefinition)
# TODO: assignments will still not be functional in the admin pages without custom logic
admin.site.register(RoleUserAssignment)
admin.site.register(RoleTeamAssignment)
admin.site.register(ObjectRole, ReadOnlyAdmin)
admin.site.register(RoleEvaluation, ReadOnlyAdmin)
