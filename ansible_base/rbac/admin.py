from django.contrib import admin

from ansible_base.lib.admin import ReadOnlyAdmin
from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleEvaluation, RoleTeamAssignment, RoleUserAssignment

admin.site.register(RoleDefinition)
# TODO: assignments will still not be functional in the admin pages without custom logic
admin.site.register(RoleUserAssignment)
admin.site.register(RoleTeamAssignment)
admin.site.register(ObjectRole, ReadOnlyAdmin)
admin.site.register(RoleEvaluation, ReadOnlyAdmin)
