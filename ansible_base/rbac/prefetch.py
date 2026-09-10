from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator, Sequence
from typing import Union
from uuid import UUID

from .models.content_type import DABContentType
from .models.permission import DABPermission
from .models.role import ObjectRole, RoleDefinition, RoleEvaluation, RoleEvaluationUUID, RoleTeamAssignment

PartialKey = tuple[str, int, Union[int, UUID]]


class TypesPrefetch:
    """Caches RoleDefinitions, permissions, and content types in memory.

    These are small, read-heavy datasets that are safe to hold for the
    lifetime of a recompute.  Use from_db() to construct a populated
    instance from the database.
    """

    def __init__(self) -> None:
        self._content_types: dict[int, DABContentType] = {}
        self._role_definitions: dict[int, RoleDefinition] = {}
        self._permissions: dict[int, DABPermission] = {}
        self._rd_permissions: dict[int, list[int]] = {}

    @classmethod
    def from_db(cls) -> TypesPrefetch:
        inst = cls()
        for rd in RoleDefinition.objects.prefetch_related('permissions__content_type'):
            inst._role_definitions[rd.id] = rd
            perm_list: list[int] = []
            for perm in rd.permissions.all():
                if perm.id not in inst._permissions:
                    inst._permissions[perm.id] = perm
                perm_list.append(perm.id)
                if perm.content_type_id not in inst._content_types:
                    inst._content_types[perm.content_type_id] = perm.content_type
            inst._rd_permissions[rd.id] = perm_list
        return inst

    def get_content_type(self, ct_id: int) -> DABContentType:
        if ct_id not in self._content_types:
            self._content_types[ct_id] = DABContentType.objects.get_for_id(ct_id)
        return self._content_types[ct_id]

    def permissions_for_object_role(self, role: ObjectRole) -> Iterator[DABPermission]:
        if role.role_definition_id not in self._rd_permissions:
            perm_id_list: list[int] = []
            for perm in role.role_definition.permissions.all():
                self._permissions[perm.id] = perm
                perm_id_list.append(perm.id)
            self._rd_permissions[role.role_definition_id] = perm_id_list
        for permission_id in self._rd_permissions[role.role_definition_id]:
            yield self._permissions[permission_id]


class EvaluationsPrefetch:
    """Batch-loaded RoleEvaluation data for a chunk of ObjectRoles.

    Avoids both N+1 queries (one per role) and full model materialization
    (which prefetch_related would do). Only the columns needed by
    needed_cache_updates are fetched, grouped by role PK.

    Public interface — used by ObjectRole.needed_cache_updates:
        get_partials(role_pk)      -> existing int-pk evaluations
        get_partials_uuid(role_pk) -> existing uuid-pk evaluations
        get_team_roles(role_pk)    -> team ObjectRoles via provides_teams chain
    """

    def __init__(self) -> None:
        self._partials: dict[int, dict[PartialKey, int]] = {}
        self._partials_uuid: dict[int, dict[PartialKey, int]] = {}
        self._team_roles: dict[int, list[ObjectRole]] = {}

    # -- public getters (consumed by ObjectRole.needed_cache_updates) --

    def get_partials(self, role_pk: int) -> dict[PartialKey, int]:
        """Existing evaluations for role_pk: {(codename, ct_id, obj_id): eval_id}."""
        return self._partials.get(role_pk, {})

    def get_partials_uuid(self, role_pk: int) -> dict[PartialKey, int]:
        """Same as get_partials but from the UUID evaluation table."""
        return self._partials_uuid.get(role_pk, {})

    def get_team_roles(self, role_pk: int) -> list[ObjectRole]:
        """ObjectRoles reachable via provides_teams -> has_roles for role_pk."""
        return self._team_roles.get(role_pk, [])

    # -- factory --

    @classmethod
    def from_roles(cls, roles: Sequence[ObjectRole]) -> EvaluationsPrefetch:
        inst = cls()
        if not roles:
            return inst

        role_pks = [r.pk for r in roles]

        inst._partials = cls._fetch_evaluations(RoleEvaluation, role_pks)
        inst._partials_uuid = cls._fetch_evaluations(RoleEvaluationUUID, role_pks)

        role_to_teams = cls._fetch_role_to_teams(role_pks)
        team_to_role_pks = cls._fetch_team_to_role_pks(role_to_teams)
        team_roles_by_pk = cls._fetch_team_role_instances(team_to_role_pks)

        for pk in role_pks:
            candidate_pks: set[int] = set()
            for team_id in role_to_teams.get(pk, []):
                candidate_pks.update(team_to_role_pks.get(team_id, []))
            inst._team_roles[pk] = [team_roles_by_pk[rpk] for rpk in candidate_pks if rpk in team_roles_by_pk]

        return inst

    # -- internal loading steps --

    @staticmethod
    def _fetch_evaluations(model: type, role_pks: list[int]) -> dict[int, dict[PartialKey, int]]:
        by_role: dict[int, dict[PartialKey, int]] = defaultdict(dict)
        for role_id, eval_id, codename, ct_id, obj_id in model.objects.filter(role_id__in=role_pks).values_list(
            'role_id', 'id', 'codename', 'content_type_id', 'object_id'
        ):
            by_role[role_id][(codename, ct_id, obj_id)] = eval_id
        return {pk: by_role.get(pk, {}) for pk in role_pks}

    @staticmethod
    def _fetch_role_to_teams(role_pks: list[int]) -> dict[int, list[int]]:
        role_to_teams: dict[int, list[int]] = defaultdict(list)
        for role_id, team_id in ObjectRole.provides_teams.through.objects.filter(objectrole_id__in=role_pks).values_list('objectrole_id', 'team_id'):
            role_to_teams[role_id].append(team_id)
        return role_to_teams

    @staticmethod
    def _fetch_team_to_role_pks(role_to_teams: dict[int, list[int]]) -> dict[int, list[int]]:
        all_team_ids = {tid for tids in role_to_teams.values() for tid in tids}
        team_to_role_pks: dict[int, list[int]] = defaultdict(list)
        if all_team_ids:
            for team_id, obj_role_id in RoleTeamAssignment.objects.filter(team_id__in=all_team_ids).values_list('team_id', 'object_role_id'):
                team_to_role_pks[team_id].append(obj_role_id)
        return team_to_role_pks

    @staticmethod
    def _fetch_team_role_instances(team_to_role_pks: dict[int, list[int]]) -> dict[int, ObjectRole]:
        all_role_pks = {rpk for rpks in team_to_role_pks.values() for rpk in rpks}
        if not all_role_pks:
            return {}
        return {r.pk: r for r in ObjectRole.objects.filter(pk__in=all_role_pks)}
