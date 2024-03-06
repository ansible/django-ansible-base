from django.contrib.contenttypes.models import ContentType


class TypesPrefetch:
    "Custom class to manage prefetching the models we know to be acceptable in memory"

    def __init__(self):
        self._content_types = {}
        self._role_definitions = {}
        self._permissions = {}
        self._rd_permissions = {}

    @classmethod
    def from_database(cls, RoleDefinition):
        inst = cls()
        for rd in RoleDefinition.objects.prefetch_related('permissions__content_type'):
            inst._role_definitions[rd.id] = rd
            perm_list = []
            for perm in rd.permissions.all():
                if perm.id not in inst._permissions:
                    inst._permissions[perm.id] = perm
                perm_list.append(perm.id)
                if perm.content_type_id not in inst._content_types:
                    inst._content_types[perm.content_type_id] = perm.content_type
            inst._rd_permissions[rd.id] = perm_list
        return inst

    def get_content_type(self, ct_id):
        if ct_id not in self._content_types:
            self._content_types[ct_id] = ContentType.objects.get_for_id(ct_id)
        return self._content_types[ct_id]

    def permissions_for_object_role(self, role):
        if role.role_definition_id not in self._rd_permissions:
            perm_id_list = []
            for perm in role.role_definition.permissions.all():
                self._permissions[perm.id] = perm
                perm_id_list.append(perm.id)
            self._rd_permissions[role.role_definition_id] = perm_id_list
        for permission_id in self._rd_permissions[role.role_definition_id]:
            yield self._permissions[permission_id]
