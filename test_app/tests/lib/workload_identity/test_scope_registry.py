from ansible_base.lib.workload_identity import SCOPE_REGISTRY, AutomationControllerJobScope


def test_scope_registry_contains_controller_scope():
    """Test that SCOPE_REGISTRY contains the AutomationControllerJobScope."""
    assert "aap_controller_automation_job" in SCOPE_REGISTRY
    assert SCOPE_REGISTRY["aap_controller_automation_job"] == AutomationControllerJobScope


def test_scope_registry_lookup():
    """Test that we can look up scopes by name."""
    scope_class = SCOPE_REGISTRY.get("aap_controller_automation_job")
    assert scope_class is not None
    assert scope_class.name == "aap_controller_automation_job"
    assert scope_class == AutomationControllerJobScope


def test_scope_registry_unknown_scope():
    """Test that looking up an unknown scope returns None."""
    scope_class = SCOPE_REGISTRY.get("unknown_scope")
    assert scope_class is None
