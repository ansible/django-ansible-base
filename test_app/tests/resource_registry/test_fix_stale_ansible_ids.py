import uuid
from unittest.mock import patch

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.management import CommandError, call_command
from django.db import connection

from ansible_base.resource_registry.models import Resource


def _insert_duplicate_resource(ct, object_id, name):
    """Insert a duplicate Resource entry via raw SQL (unique constraint must be dropped first)."""
    ansible_id = uuid.uuid4()
    with connection.cursor() as cursor:
        cursor.execute("SELECT service_id FROM dab_resource_registry_resource LIMIT 1")
        row = cursor.fetchone()
        service_id = row[0] if row else str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO dab_resource_registry_resource "
            "(ansible_id, content_type_id, object_id, name, service_id, is_partially_migrated) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            [str(ansible_id), ct.pk, str(object_id), name, service_id, False],
        )
    return ansible_id


@pytest.mark.django_db
class TestFixStaleAnsibleIds:
    def test_audit_all_ok(self, team, organization, capsys):
        call_command("fix_stale_ansible_ids")
        captured = capsys.readouterr()
        assert "All resource types OK" in captured.out

    def test_audit_specific_type(self, team, capsys):
        call_command("fix_stale_ansible_ids", "team")
        captured = capsys.readouterr()
        assert "shared.team" in captured.out
        assert "shared.organization" not in captured.out

    def test_audit_with_shared_prefix(self, team, capsys):
        call_command("fix_stale_ansible_ids", "shared.team")
        captured = capsys.readouterr()
        assert "shared.team" in captured.out

    def test_detect_missing_entry(self, team, capsys):
        ct = ContentType.objects.get_for_model(team)
        Resource.objects.filter(content_type=ct, object_id=str(team.pk)).delete()

        call_command("fix_stale_ansible_ids", "team")
        captured = capsys.readouterr()
        assert "Missing Resource entries: 1" in captured.out
        assert team.name in captured.out
        assert "Run with --fix" in captured.out

    def test_fix_missing_entry(self, team, capsys):
        ct = ContentType.objects.get_for_model(team)
        Resource.objects.filter(content_type=ct, object_id=str(team.pk)).delete()
        assert not Resource.objects.filter(content_type=ct, object_id=str(team.pk)).exists()

        call_command("fix_stale_ansible_ids", "team", fix=True)
        captured = capsys.readouterr()
        assert "Created 1 Resource entries" in captured.out
        assert "resource_sync" in captured.out

        resource = Resource.objects.get(content_type=ct, object_id=str(team.pk))
        assert resource.name == team.name
        assert resource.ansible_id is not None

    def test_fix_is_idempotent(self, team, capsys):
        ct = ContentType.objects.get_for_model(team)
        Resource.objects.filter(content_type=ct, object_id=str(team.pk)).delete()

        call_command("fix_stale_ansible_ids", "team", fix=True)
        resource = Resource.objects.get(content_type=ct, object_id=str(team.pk))
        first_id = resource.ansible_id

        call_command("fix_stale_ansible_ids", "team", fix=True)
        captured = capsys.readouterr()
        assert "All instances have Resource entries" in captured.out

        resource.refresh_from_db()
        assert resource.ansible_id == first_id

    def test_detect_orphan_resource(self, team, capsys):
        ct = ContentType.objects.get_for_model(team)
        Resource.objects.create(
            content_type=ct,
            object_id="999999",
            name="ghost_team",
        )

        call_command("fix_stale_ansible_ids", "team")
        captured = capsys.readouterr()
        assert "Orphan Resource entries" in captured.out

    def test_no_matching_types(self):
        with pytest.raises(CommandError, match="Unknown resource type"):
            call_command("fix_stale_ansible_ids", "nonexistent")

    def test_partial_unknown_type_raises_error(self, team):
        with pytest.raises(CommandError, match="shared.organizaton"):
            call_command("fix_stale_ansible_ids", "team", "organizaton")

    def test_multiple_missing_entries(self, organization, capsys):
        from test_app.models import Team

        teams = [Team.objects.create(name=f"test_team_{i}", organization=organization) for i in range(3)]
        ct = ContentType.objects.get_for_model(teams[0])
        Resource.objects.filter(content_type=ct, object_id__in=[str(t.pk) for t in teams]).delete()

        call_command("fix_stale_ansible_ids", "team", fix=True)
        captured = capsys.readouterr()
        assert "Created 3 Resource entries" in captured.out

        for t in teams:
            assert Resource.objects.filter(content_type=ct, object_id=str(t.pk)).exists()

    def test_orphan_summary(self, team, organization, capsys):
        ct = ContentType.objects.get_for_model(team)
        Resource.objects.create(content_type=ct, object_id="888888", name="orphan1")
        Resource.objects.create(content_type=ct, object_id="888889", name="orphan2")

        call_command("fix_stale_ansible_ids", "team")
        captured = capsys.readouterr()
        assert "2 orphan Resource entries" in captured.out
        assert "No action needed" in captured.out

    def test_fix_missing_summary_with_fix_flag(self, team, capsys):
        ct = ContentType.objects.get_for_model(team)
        Resource.objects.filter(content_type=ct, object_id=str(team.pk)).delete()

        call_command("fix_stale_ansible_ids", "team", fix=True)
        captured = capsys.readouterr()
        assert "Created 1 missing Resource entries." in captured.out
        assert "resource_sync" in captured.out

    def test_no_resource_types_found(self, capsys):
        with patch("ansible_base.resource_registry.management.commands.fix_stale_ansible_ids.ResourceType.objects") as mock_qs:
            mock_qs.all.return_value = mock_qs
            mock_qs.filter.return_value = mock_qs
            mock_qs.exists.return_value = False
            call_command("fix_stale_ansible_ids")
        captured = capsys.readouterr()
        assert "No matching resource types found" in captured.err

    def test_model_class_not_found(self, team, capsys):
        with patch.object(ContentType, "model_class", return_value=None):
            call_command("fix_stale_ansible_ids", "team")
        captured = capsys.readouterr()
        assert "Skipping" in captured.err
        assert "model class not found" in captured.err

    def test_report_sample_overflow(self, organization, capsys):
        from test_app.models import Team

        teams = [Team.objects.create(name=f"overflow_team_{i}", organization=organization) for i in range(12)]
        ct = ContentType.objects.get_for_model(teams[0])
        Resource.objects.filter(content_type=ct, object_id__in=[str(t.pk) for t in teams]).delete()

        call_command("fix_stale_ansible_ids", "team")
        captured = capsys.readouterr()
        assert "Missing Resource entries: 12" in captured.out
        assert "... and 2 more" in captured.out


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor == 'sqlite', reason='ALTER TABLE constraint operations not supported on SQLite')
class TestFixStaleAnsibleIdsDuplicates:
    """Tests for duplicate detection/repair — requires transaction=True for DDL (ALTER TABLE)."""

    @pytest.fixture(autouse=True)
    def _setup_team_with_duplicate(self, organization):
        from test_app.models import Team

        self.team = Team.objects.create(name="dupe_test_team", organization=organization)
        self.ct = ContentType.objects.get_for_model(self.team)
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE dab_resource_registry_resource DROP CONSTRAINT IF EXISTS unique_resource_content_type_object_id")
            cursor.execute("DROP INDEX IF EXISTS unique_resource_content_type_object_id")
        _insert_duplicate_resource(self.ct, self.team.pk, self.team.name)
        yield
        Resource.objects.filter(content_type=self.ct, object_id=str(self.team.pk)).exclude(
            pk=Resource.objects.filter(content_type=self.ct, object_id=str(self.team.pk)).order_by("pk").values("pk")[:1]
        ).delete()
        self.team.delete()
        with connection.cursor() as cursor:
            cursor.execute("DROP INDEX IF EXISTS unique_resource_content_type_object_id")
            cursor.execute(
                "ALTER TABLE dab_resource_registry_resource ADD CONSTRAINT unique_resource_content_type_object_id "
                "UNIQUE (content_type_id, object_id) INCLUDE (ansible_id)"
            )

    def test_detect_duplicates_audit_only(self, capsys):
        call_command("fix_stale_ansible_ids", "team")
        captured = capsys.readouterr()
        assert "DUPLICATE Resource entries: 1" in captured.out
        assert "Run with --deduplicate" in captured.out

    def test_fix_duplicates(self, capsys):
        original = Resource.objects.filter(content_type=self.ct, object_id=str(self.team.pk)).order_by("pk").first()
        original_ansible_id = original.ansible_id

        call_command("fix_stale_ansible_ids", "team", deduplicate=True)
        captured = capsys.readouterr()
        assert "Removed 1 duplicate Resource entries" in captured.out
        assert "Kept ansible_id=" in captured.out

        remaining = Resource.objects.filter(content_type=self.ct, object_id=str(self.team.pk))
        assert remaining.count() == 1
        assert remaining.first().ansible_id == original_ansible_id

    def test_fix_duplicates_summary(self, capsys):
        call_command("fix_stale_ansible_ids", "team", deduplicate=True)
        captured = capsys.readouterr()
        assert "Removed 1 duplicate Resource entries." in captured.out

    def test_duplicates_reported_in_audit_summary(self, capsys):
        call_command("fix_stale_ansible_ids", "team")
        captured = capsys.readouterr()
        assert "1 duplicate Resource entries" in captured.out
        assert "deduplicate" in captured.out
        assert "All resource types OK" not in captured.out
