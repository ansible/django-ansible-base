from ansible_base.lib.routers import AssociationResourceRouter

from . import views

service_router = AssociationResourceRouter()

service_router.register(r'role-types', views.RoleContentTypeViewSet)
service_router.register(r'role-permissions', views.RolePermissionTypeViewSet)
# Different basenames used to distinguish between the duplicate, public, endpoints
service_router.register(r'role-user-assignments', views.ServiceRoleUserAssignmentViewSet, basename='serviceuserassignment')
service_router.register(r'role-team-assignments', views.ServiceRoleTeamAssignmentViewSet, basename='serviceteamassignment')
