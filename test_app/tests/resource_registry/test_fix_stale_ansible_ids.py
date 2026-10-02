import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command

from ansible_base.resource_registry.models import Resource


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

    def test_no_matching_types(self, capsys):
        call_command("fix_stale_ansible_ids", "nonexistent")
        captured = capsys.readouterr()
        assert "No matching resource types" in captured.err

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
