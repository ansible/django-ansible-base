# x-ai-description Generation Guide

## Overview

The `x-ai-description` field is automatically generated for all API endpoints and is used by MCP (Model Context Protocol) servers to provide better context to AI tools about API operations.

## How It Works

The postprocessing hook automatically:
1. Extracts the operation type (list, create, update, delete, etc.)
2. Prepends an action verb to your endpoint's description
3. Generates concise, AI-friendly descriptions

### Example Transformations

| Your Description | Operation | Generated x-ai-description |
|------------------|-----------|---------------------------|
| "groups to be viewed or edited" | GET (list) | "List all groups" |
| "groups to be viewed or edited" | POST (create) | "Create new group" |
| "groups to be viewed or edited" | DELETE (destroy) | "Delete existing group" |
| "status of platform services" | GET (retrieve) | "Retrieve single status of platform services" |

## Writing Good Descriptions

### Guidelines

**DO write descriptions that explain WHAT and WHY:**
- ✅ "teams for organizing users and managing group permissions"
- ✅ "activity stream entries for auditing system changes"
- ✅ "HTTP port configurations for routing traffic to backend services"

**DON'T include the action verb (it's added automatically):**
- ❌ "List all teams"
- ❌ "Create a new organization"
- ❌ "Retrieve user details"

**DON'T use generic boilerplate:**
- ❌ "API endpoint that allows teams to be viewed or edited"
- ❌ "API endpoint for managing users"

### Sentence Structure

Use this pattern in your ViewSet/APIView docstrings:

```
"<resource> for <purpose/why it's used>"
```

**Examples:**
```python
class TeamViewSet(ModelViewSet):
    """
    teams for organizing users and managing group permissions
    """
    queryset = Team.objects.all()
    serializer_class = TeamSerializer
```

```python
class ActivityStreamViewSet(ReadOnlyModelViewSet):
    """
    activity stream entries for auditing system changes and compliance tracking
    """
    queryset = ActivityStream.objects.all()
    serializer_class = ActivityStreamSerializer
```

```python
class StatusView(APIView):
    """
    platform service status for monitoring system health
    """
    def get(self, request):
        ...
```

## Character Limits

- **Preferred:** < 200 characters
- **Maximum:** < 300 characters (enforced with truncation)

The hook will log warnings if descriptions exceed these limits.

## Opting Out

If you need to disable automatic x-ai-description generation for a specific ViewSet/APIView, set:

```python
class MyCustomViewSet(ModelViewSet):
    skip_ai_description = True
    queryset = MyModel.objects.all()
    serializer_class = MySerializer
```

## Explicit Override

To provide a custom x-ai-description for a specific operation, use `@extend_schema`:

```python
from drf_spectacular.utils import extend_schema

class TeamViewSet(ModelViewSet):
    """teams for organizing users"""

    @extend_schema(
        operation_id='teams_special_action',
        responses={200: TeamSerializer},
        **{'x-ai-description': 'Perform special team synchronization operation'}
    )
    @action(detail=False, methods=['post'])
    def sync(self, request):
        ...
```

## Current State Analysis

Based on existing Gateway endpoints, most descriptions follow this pattern:
- ❌ "API endpoint that allows X to be viewed or edited"

**Recommended migration:**
- ✅ "X for <purpose>"

### Migration Examples

**Before:**
```python
"""API endpoint that allows teams to be viewed or edited."""
```

**After:**
```python
"""teams for organizing users and managing group permissions"""
```

---

**Before:**
```python
"""API endpoint that allows authenticators to be viewed or edited."""
```

**After:**
```python
"""authenticators for configuring user authentication methods (LDAP, SAML, OAuth)"""
```

---

**Before:**
```python
"""API endpoint that shows status of platform services."""
```

**After:**
```python
"""platform service status for monitoring system health and availability"""
```

## Testing Your Descriptions

After updating descriptions, verify the generated x-ai-description by:

1. Regenerating the OpenAPI schema
2. Checking the x-ai-description field for your endpoints
3. Ensuring descriptions are:
   - Clear and concise
   - Under 200 characters (preferred) or 300 characters (maximum)
   - Describe WHAT and WHY, not HOW

## Questions?

See the postprocessing hook implementation at:
`ansible_base/api_documentation/postprocessing_hooks.py`
