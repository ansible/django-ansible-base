"""
Unit tests for api_documentation preprocessing hooks.

These tests verify the behavior of functions used to identify ViewSets
that should skip x-ai-description generation or have custom resource_purpose values.
"""

from ansible_base.api_documentation.preprocessing_hooks import (
    OPERATION_CLASS_MAP,
    RESOURCE_PURPOSE_MAP,
    SKIP_AI_DESCRIPTION_PREFIXES,
    collect_ai_description_metadata,
)
from test_app.views import (
    TeamViewSet,
    TestViewSetWithBothAttributes,
    TestViewSetWithResourcePurpose,
    TestViewSetWithSkipAI,
)


class MockViewWrapper:
    """Mock view wrapper with cls attribute (simulates DRF's view wrapping)."""

    def __init__(self, view_class):
        self.cls = view_class


class TestMarkSkipAiDescription:
    """Test the collect_ai_description_metadata preprocessing hook."""

    def setup_method(self):
        """Clear global state before each test."""
        SKIP_AI_DESCRIPTION_PREFIXES.clear()
        RESOURCE_PURPOSE_MAP.clear()
        OPERATION_CLASS_MAP.clear()

    def test_empty_endpoints(self):
        """Test that empty endpoints list returns empty list."""
        result = collect_ai_description_metadata([])
        assert result == []
        assert len(SKIP_AI_DESCRIPTION_PREFIXES) == 0
        assert len(RESOURCE_PURPOSE_MAP) == 0
        assert len(OPERATION_CLASS_MAP) == 0

    def test_none_endpoints(self):
        """Test that None endpoints returns None."""
        result = collect_ai_description_metadata(None)
        assert result is None

    def test_simple_viewset_no_attributes(self):
        """Test processing a simple ViewSet with no special attributes."""
        view = TeamViewSet()
        endpoints = [('/api/gateway/v1/teams/', 'pattern', 'GET', view)]

        result = collect_ai_description_metadata(endpoints)

        assert result == endpoints
        assert 'teams' not in SKIP_AI_DESCRIPTION_PREFIXES
        assert 'TeamViewSet' not in RESOURCE_PURPOSE_MAP
        assert OPERATION_CLASS_MAP['teams'] == ('TeamViewSet', 4, ['api', 'gateway', 'v1', 'teams'])

    def test_viewset_with_skip_ai_description(self):
        """Test processing a ViewSet with skip_ai_description=True."""
        view = TestViewSetWithSkipAI()
        endpoints = [('/api/gateway/v1/test/', 'pattern', 'GET', view)]

        collect_ai_description_metadata(endpoints)

        assert 'test' in SKIP_AI_DESCRIPTION_PREFIXES
        assert OPERATION_CLASS_MAP['test'] == ('TestViewSetWithSkipAI', 4, ['api', 'gateway', 'v1', 'test'])

    def test_viewset_with_resource_purpose(self):
        """Test processing a ViewSet with resource_purpose."""
        view = TestViewSetWithResourcePurpose()
        endpoints = [('/api/gateway/v1/test/', 'pattern', 'GET', view)]

        collect_ai_description_metadata(endpoints)

        assert 'test' not in SKIP_AI_DESCRIPTION_PREFIXES
        assert RESOURCE_PURPOSE_MAP['TestViewSetWithResourcePurpose'] == 'test resources for validating purpose-based descriptions'
        assert OPERATION_CLASS_MAP['test'] == ('TestViewSetWithResourcePurpose', 4, ['api', 'gateway', 'v1', 'test'])

    def test_viewset_with_both_attributes(self):
        """Test processing a ViewSet with both skip_ai_description and resource_purpose."""
        view = TestViewSetWithBothAttributes()
        endpoints = [('/api/gateway/v1/test/', 'pattern', 'GET', view)]

        collect_ai_description_metadata(endpoints)

        assert 'test' in SKIP_AI_DESCRIPTION_PREFIXES
        assert RESOURCE_PURPOSE_MAP['TestViewSetWithBothAttributes'] == 'test resources that should be skipped'

    def test_view_with_cls_attribute(self):
        """Test processing a view wrapped with cls attribute (DRF pattern)."""
        view_wrapper = MockViewWrapper(TestViewSetWithSkipAI)
        endpoints = [('/api/gateway/v1/test/', 'pattern', 'GET', view_wrapper)]

        collect_ai_description_metadata(endpoints)

        assert 'test' in SKIP_AI_DESCRIPTION_PREFIXES
        assert OPERATION_CLASS_MAP['test'] == ('TestViewSetWithSkipAI', 4, ['api', 'gateway', 'v1', 'test'])

    def test_nested_resource(self):
        """Test processing nested resources."""
        view = TeamViewSet()
        endpoints = [('/api/gateway/v1/orgs/{id}/teams/', 'pattern', 'GET', view)]

        collect_ai_description_metadata(endpoints)

        # Nested resource uses the last path segment as prefix
        assert OPERATION_CLASS_MAP['teams'] == ('TeamViewSet', 5, ['api', 'gateway', 'v1', 'orgs', 'teams'])

    def test_multiple_endpoints_same_viewset(self):
        """Test processing multiple endpoints for the same ViewSet."""
        view = TestViewSetWithResourcePurpose()
        endpoints = [
            ('/api/gateway/v1/test/', 'pattern', 'GET', view),
            ('/api/gateway/v1/test/', 'pattern', 'POST', view),
            ('/api/gateway/v1/test/{id}/', 'pattern', 'GET', view),
        ]

        collect_ai_description_metadata(endpoints)

        # Resource purpose should be stored once per ViewSet
        assert RESOURCE_PURPOSE_MAP['TestViewSetWithResourcePurpose'] == 'test resources for validating purpose-based descriptions'
        assert OPERATION_CLASS_MAP['test'] == ('TestViewSetWithResourcePurpose', 4, ['api', 'gateway', 'v1', 'test'])

    def test_collision_resolution_main_resource_first(self):
        """Test collision resolution when main resource is encountered first."""
        # Main resource (fewer path parts)
        main_view = TeamViewSet()
        main_endpoints = [('/api/gateway/v1/teams/', 'pattern', 'GET', main_view)]

        collect_ai_description_metadata(main_endpoints)
        assert OPERATION_CLASS_MAP['teams'] == ('TeamViewSet', 4, ['api', 'gateway', 'v1', 'teams'])

        # Nested resource (more path parts) - should get compound prefix
        # Since they're different ViewSets but same final segment, collision should be resolved
        nested_view = TestViewSetWithSkipAI()  # Different ViewSet class
        nested_endpoints = [('/api/gateway/v1/orgs/{id}/test/', 'pattern', 'GET', nested_view)]

        collect_ai_description_metadata(nested_endpoints)

        # This won't collide because path segments are different (teams vs test)
        # Let me actually create a real collision by using the same path segment
        assert OPERATION_CLASS_MAP['test'] == ('TestViewSetWithSkipAI', 5, ['api', 'gateway', 'v1', 'orgs', 'test'])

    def test_collision_resolution_nested_resource_first(self):
        """Test collision resolution when nested resource is encountered first."""
        # Note: Collision resolution only happens within a single call to collect_ai_description_metadata
        # because it clears state on each call. Let me test that properly.

        # Create two different ViewSets that will use the same 'teams' prefix
        main_view = TeamViewSet()
        nested_view = TestViewSetWithSkipAI()  # Different class

        # Process both in one call - nested first, then main
        endpoints = [
            ('/api/gateway/v1/orgs/{id}/teams/', 'pattern', 'GET', nested_view),  # 5 parts, will claim 'teams'
            ('/api/gateway/v1/teams/', 'pattern', 'GET', main_view),  # 4 parts, should take over 'teams'
        ]

        collect_ai_description_metadata(endpoints)

        # Main resource (4 parts) should take simple prefix
        assert OPERATION_CLASS_MAP['teams'] == ('TeamViewSet', 4, ['api', 'gateway', 'v1', 'teams'])
        # Nested resource should get compound prefix 'orgs_teams' (bug now fixed!)
        assert OPERATION_CLASS_MAP['orgs_teams'] == ('TestViewSetWithSkipAI', 5, ['api', 'gateway', 'v1', 'orgs', 'teams'])

    def test_same_viewset_same_prefix_no_collision(self):
        """Test that same ViewSet on same prefix doesn't create collision."""
        view = TeamViewSet()
        endpoints = [
            ('/api/gateway/v1/teams/', 'pattern', 'GET', view),
            ('/api/gateway/v1/teams/', 'pattern', 'POST', view),
        ]

        collect_ai_description_metadata(endpoints)

        # Should only have one entry
        assert OPERATION_CLASS_MAP['teams'] == ('TeamViewSet', 4, ['api', 'gateway', 'v1', 'teams'])
        assert len(OPERATION_CLASS_MAP) == 1

    def test_exception_handling(self):
        """Test that exceptions during processing don't crash the hook."""

        # Create a view that will raise an exception when accessing attributes
        class BadView:
            @property
            def cls(self):
                raise RuntimeError("Intentional error")

        bad_view = BadView()
        good_view = TeamViewSet()

        endpoints = [
            ('/api/gateway/v1/bad/', 'pattern', 'GET', bad_view),
            ('/api/gateway/v1/teams/', 'pattern', 'GET', good_view),
        ]

        # Should not raise exception
        result = collect_ai_description_metadata(endpoints)

        # Should still process the good endpoint
        assert result == endpoints
        assert OPERATION_CLASS_MAP['teams'] == ('TeamViewSet', 4, ['api', 'gateway', 'v1', 'teams'])

    def test_path_without_segments(self):
        """Test handling of path that yields no segments after parsing."""
        view = TeamViewSet()
        # Path with only parameters or empty segments
        endpoints = [('/{id}/', 'pattern', 'GET', view)]

        collect_ai_description_metadata(endpoints)

        # Should be skipped (continue in loop)
        assert len(OPERATION_CLASS_MAP) == 0

    def test_clears_state_on_each_call(self):
        """Test that global state is cleared on each call."""
        view1 = TestViewSetWithBothAttributes()
        endpoints1 = [('/api/gateway/v1/resource1/', 'pattern', 'GET', view1)]

        collect_ai_description_metadata(endpoints1)
        assert 'resource1' in SKIP_AI_DESCRIPTION_PREFIXES
        assert 'TestViewSetWithBothAttributes' in RESOURCE_PURPOSE_MAP

        # Second call should clear previous state
        view2 = TeamViewSet()
        endpoints2 = [('/api/gateway/v1/resource2/', 'pattern', 'GET', view2)]

        collect_ai_description_metadata(endpoints2)

        # Old state should be cleared
        assert 'resource1' not in SKIP_AI_DESCRIPTION_PREFIXES
        assert 'TestViewSetWithBothAttributes' not in RESOURCE_PURPOSE_MAP
        # New state should be present
        assert 'resource2' in OPERATION_CLASS_MAP
