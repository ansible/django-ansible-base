# x-ai-description Generation Guide

## Overview

The `x-ai-description` field is automatically generated for all API endpoints and is used by MCP (Model Context Protocol) servers to provide better context to AI tools about API operations.

## How It Works

The system uses a **two-tier approach** to generate descriptions:

### Priority 1: Explicit x-ai-description (Highest Priority)
If you define `x-ai-description` explicitly using `@extend_schema`, it will be used as-is.

### Priority 2: resource_purpose Field (Recommended)
If you define a `resource_purpose` field on your ViewSet, the hook will generate contextual descriptions for standard CRUD operations.

### Fallback: Auto-generation
If neither of the above are present, the hook generates basic descriptions from resource names and operation types.

### Example Transformations

With `resource_purpose`:

| resource_purpose | Operation | Generated x-ai-description |
|------------------|-----------|---------------------------|
| "audit trail entries for tracking system changes" | GET (list) | "List audit trail entries for tracking system changes" |
| "audit trail entries for tracking system changes" | POST (create) | "Create an audit trail entry for tracking system changes" |
| "audit trail entries for tracking system changes" | GET (retrieve) | "Retrieve an audit trail entry for tracking system changes" |
| "audit trail entries for tracking system changes" | DELETE (destroy) | "Delete an audit trail entry for tracking system changes" |

## Writing Good Descriptions

### Using resource_purpose (Recommended)

The `resource_purpose` field should describe:
- **WHAT** the resource is (plural noun phrase)
- **WHY** it exists or when an MCP tool would use it

**Pattern:**
```
"<resource_plural> for <purpose/use_case>"
```

**Examples:**

```python
class ActivityStreamViewSet(ReadOnlyModelViewSet):
    """API endpoint for activity stream entries."""

    resource_purpose = "audit trail entries for tracking system changes and user actions"

    queryset = ActivityStream.objects.all()
    serializer_class = ActivityStreamSerializer
```

```python
class AuthenticatorViewSet(ModelViewSet):
    """API endpoint for authenticators."""

    resource_purpose = "authentication providers for configuring user login methods (LDAP, SAML, OAuth)"

    queryset = Authenticator.objects.all()
    serializer_class = AuthenticatorSerializer
```

```python
class RoleDefinitionViewSet(ModelViewSet):
    """API endpoint for role definitions."""

    resource_purpose = "RBAC role templates defining permissions that can be assigned to users and teams"

    queryset = RoleDefinition.objects.all()
    serializer_class = RoleDefinitionSerializer
```

### Guidelines for resource_purpose

**DO explain WHAT and WHY:**
- ✅ "authentication providers for configuring user login methods (LDAP, SAML, OAuth)"
- ✅ "audit trail entries for tracking system changes and user actions"
- ✅ "HTTP listener ports for routing incoming traffic to backend services"

**DON'T include action verbs (they're added automatically):**
- ❌ "List authentication providers"
- ❌ "Create new audit trail entries"
- ❌ "Manage HTTP ports"

**DON'T use generic boilerplate:**
- ❌ "resources that can be viewed or edited"
- ❌ "objects for managing system configuration"

**DO use plural nouns** (the hook will singularize for create/update/delete/retrieve):
- ✅ "audit trail entries" → becomes "audit trail entry" for create/retrieve
- ✅ "authentication providers" → becomes "authentication provider" for update
- ✅ "HTTP listener ports" → becomes "HTTP listener port" for delete

## Character Limits

- **Preferred:** < 200 characters
- **Maximum:** < 300 characters (enforced with truncation)

The hook will automatically truncate descriptions that exceed 300 characters.

**Tips for staying under 200 chars:**
- Focus on the essential purpose
- Use parentheses for examples: "(LDAP, SAML, OAuth)"
- Avoid redundant words: "for" instead of "used for"

## When to Use Each Approach

### Use `resource_purpose` when:
- ✅ The resource is **domain-specific** or uses technical jargon (e.g., "RBAC role templates", "JWT signing keys", "authentication providers")
- ✅ The resource purpose isn't immediately obvious from its name (e.g., "authenticator maps" → "attribute mapping rules")
- ✅ The resource needs contextual explanation for MCP tool selection (e.g., "audit trail entries for tracking system changes")
- ✅ You have standard CRUD operations that all share the same core purpose

### Use `@extend_schema` with explicit `x-ai-description` when:
- ✅ You have custom actions beyond CRUD
- ✅ An operation needs unique context different from the resource purpose
- ✅ You need fine-grained control over the description

### Prefer auto-generation (no resource_purpose) when:
- ✅ The resource is **self-explanatory** (e.g., "teams", "users", "organizations")
- ✅ The resource name clearly conveys its purpose
- ✅ No domain-specific context is needed for MCP tool selection

**Philosophy:** `resource_purpose` should be used sparingly. Docstrings serve human developers; `resource_purpose` serves AI tool selection. Only add `resource_purpose` when it provides meaningful context that auto-generation cannot capture.

### Example combining both:

```python
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action

class AuthenticatorViewSet(ModelViewSet):
    """API endpoint for authenticators."""

    # Handles list, create, retrieve, update, delete automatically
    resource_purpose = "authentication providers for configuring user login methods (LDAP, SAML, OAuth)"

    queryset = Authenticator.objects.all()
    serializer_class = AuthenticatorSerializer

    # Custom action needs explicit description
    @extend_schema(
        extensions={'x-ai-description': 'Test authenticator connection and validate configuration'}
    )
    @action(detail=True, methods=['post'])
    def test(self, request, pk=None):
        """Test authenticator connectivity"""
        ...
```

## Opting Out

If you need to disable automatic x-ai-description generation for a specific ViewSet/APIView, set:

```python
class MyCustomViewSet(ModelViewSet):
    skip_ai_description = True
    queryset = MyModel.objects.all()
    serializer_class = MySerializer
```

## Separation of Concerns

**Docstrings are for human developers:**
```python
class TeamViewSet(ModelViewSet):
    """
    API endpoint for managing teams.

    Teams organize users and control group-based permissions.
    """
    queryset = Team.objects.all()
    serializer_class = TeamSerializer
```

**resource_purpose is for AI/MCP tool selection:**
```python
class AuthenticatorMapViewSet(ModelViewSet):
    """API endpoint for authenticator maps."""

    resource_purpose = "attribute mapping rules for mapping external user attributes to AAP user fields"

    queryset = AuthenticatorMap.objects.all()
    serializer_class = AuthenticatorMapSerializer
```

This separation ensures:
- ✅ Docstrings can be detailed and conversational for developers
- ✅ resource_purpose stays concise and optimized for AI tool selection
- ✅ Each serves its intended audience without compromise

## Testing Your Descriptions

After adding or updating `resource_purpose` fields:

1. Regenerate the OpenAPI schema
2. Check the generated x-ai-description fields
3. Validate using the validation script:
   ```bash
   python tools/validate_ai_descriptions.py /path/to/schema.json
   ```
4. Ensure descriptions:
   - Are clear and explain WHAT and WHY
   - Stay under 200 characters (preferred) or 300 characters (maximum)
   - Provide useful context for MCP tool selection

## Enabling Automatic x-ai-description Generation

To enable automatic `x-ai-description` generation for your OpenAPI schema, register the preprocessing and postprocessing hooks in your Django settings.

### Configuration

Add or update the `SPECTACULAR_SETTINGS` dictionary in your Django settings file:

```python
SPECTACULAR_SETTINGS = {
    # ... your existing settings ...

    'PREPROCESSING_HOOKS': [
        'ansible_base.api_documentation.preprocessing_hooks.collect_ai_description_metadata',
    ],
    'POSTPROCESSING_HOOKS': [
        'ansible_base.api_documentation.postprocessing_hooks.add_x_ai_description',
    ],
}
```

## Implementation Details

See the hook implementations:
- Preprocessing: `ansible_base/api_documentation/preprocessing_hooks.py`
- Postprocessing: `ansible_base/api_documentation/postprocessing_hooks.py`
