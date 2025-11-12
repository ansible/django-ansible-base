# x-ai-description Generation Guide

## Overview

The `x-ai-description` field is automatically generated for all API endpoints and is used by MCP (Model Context Protocol) servers to provide better context to AI tools about API operations.

**NOTE:** The generation uses the `ansible_base.lib.utils.schema.extend_schema_if_available` decorator. It functions
as a simple wrapper around `drf_spectacular.utils.extend_schema` that fails gracefully when the `drf_spectacular` dependency
is not found.

## How It Works

The system uses a **two-phase hook process** during OpenAPI schema generation:

### Phase 1: Preprocessing (Metadata Collection)

Before the OpenAPI schema is generated, the **preprocessing hook** (`collect_ai_description_metadata`) inspects all registered ViewSets and collects metadata:

1. **Scans all API endpoints** from Django's URL routing
2. **Extracts operation prefix from URL path**:
   - Example: `/api/v1/teams/` → prefix `"teams"`
   - Example: `/api/v1/http_ports/` → prefix `"http_ports"`
3. **Extracts ViewSet metadata** for each endpoint:
   - `resource_purpose` field (if defined)
   - `skip_ai_description` flag (if set)
   - ViewSet class name
4. **Creates global mappings** stored in memory:
   - `OPERATION_CLASS_MAP`: Maps operation prefixes to ViewSet class names
   - `RESOURCE_PURPOSE_MAP`: Maps ViewSet class names to their `resource_purpose` values
   - `SKIP_AI_DESCRIPTION_PREFIXES`: Tracks ViewSets that have opted out
5. **Resolves naming collisions** when multiple ViewSets share the same resource name:
   - Example: Both `/api/v1/teams/` and `/api/v1/orgs/{id}/teams/` end with "teams"
   - The main resource (`/teams/`) gets the simple prefix: `teams_list`, `teams_create`, etc.
   - The nested resource (`/orgs/{id}/teams/`) gets a compound prefix: `orgs_teams_list`, `orgs_teams_create`, etc.

### Phase 2: Postprocessing (Description Generation)

After the OpenAPI schema is fully generated, the **postprocessing hook** (`add_x_ai_description`) adds `x-ai-description` fields:

1. **Iterates through all operations** in the generated schema (`paths[path][method]`)
2. **Extracts the operation ID** (e.g., `teams_list`, `http_ports_retrieve`)
   - drf-spectacular generates operation IDs from URL paths, keeping it consistent with the preprocessing hook
   - Example: `/api/v1/http_ports/` → `http_ports_list`
3. **Extracts prefix from operation ID** to look up metadata:
   - Example: `teams_list` → prefix `"teams"`
   - Example: `http_ports_retrieve` → prefix `"http_ports"`
4. **Looks up metadata** using the operation ID prefix:
   - Checks if ViewSet opted out (`SKIP_AI_DESCRIPTION_PREFIXES`)
   - Retrieves `resource_purpose` via `OPERATION_CLASS_MAP` → `RESOURCE_PURPOSE_MAP`
5. **Generates x-ai-description** using a priority system (see below)
6. **Adds the field** to the operation in the OpenAPI schema

#### Example: Where x-ai-description Appears in the OpenAPI Schema

For a ViewSet with `resource_purpose = "audit trail entries for tracking system changes"`, the postprocessing hook adds the `x-ai-description` field to each operation in the generated OpenAPI schema:

```json
{
  "paths": {
    "/api/v1/activitystream/": {
      "get": {
        "operationId": "activitystream_list",
        "summary": "List Activity Streams",
        "description": "API endpoint for activity stream entries.",
        "x-ai-description": "List audit trail entries for tracking system changes",
        "parameters": [...],
        "responses": {...}
      },
      "post": {
        "operationId": "activitystream_create",
        "summary": "Create Activity Stream",
        "description": "API endpoint for activity stream entries.",
        "x-ai-description": "Create an audit trail entry for tracking system changes",
        "requestBody": {...},
        "responses": {...}
      }
    },
    "/api/v1/activitystream/{id}/": {
      "get": {
        "operationId": "activitystream_retrieve",
        "summary": "Retrieve Activity Stream",
        "description": "API endpoint for activity stream entries.",
        "x-ai-description": "Retrieve an audit trail entry for tracking system changes",
        "parameters": [...],
        "responses": {...}
      }
    }
  }
}
```

The hook adds `x-ai-description` at `paths[path][method]["x-ai-description"]` for each operation, using the operation ID to look up the appropriate description via the global mappings created during preprocessing.

### Description Generation Priority

The postprocessing hook uses a **three-tier priority system**:

#### Priority 1: Explicit x-ai-description
If you define `x-ai-description` explicitly using `@extend_schema_if_available`, it will be used as-is
[as seen in this example](#using-extend_schema_if_available).

#### Priority 2: resource_purpose Field
If you define a `resource_purpose` field on your ViewSet, the hook will generate contextual descriptions for standard CRUD operations
[as seen in this example](#using-resource_purpose).

#### Priority 3: Auto-generation
There's a fallback mechanism to ensure the field is present if neither of the above are used. In this scenario the hook generates basic descriptions from
resource names and operation types 
[as seen in this example](#auto-generated-descriptions).

### Example Transformations

With `resource_purpose`, the hook automatically generates descriptions for all CRUD operations:

| resource_purpose | Operation | Generated x-ai-description |
|------------------|-----------|---------------------------|
| "audit trail entries for tracking system changes" | GET (list) | "List audit trail entries for tracking system changes" |
| "audit trail entries for tracking system changes" | POST (create) | "Create an audit trail entry for tracking system changes" |
| "audit trail entries for tracking system changes" | GET (retrieve) | "Retrieve an audit trail entry for tracking system changes" |
| "audit trail entries for tracking system changes" | PUT (update) | "Update an audit trail entry for tracking system changes" |
| "audit trail entries for tracking system changes" | PATCH (partial_update) | "Update an audit trail entry for tracking system changes" |
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

[See examples](#examples)

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

### Bad Examples

**❌ Too long (exceeds 300 character limit):**
```python
resource_purpose = "authentication configuration mappings that define how external identity provider attributes should be transformed and applied to local user accounts, including complex rule-based matching for organizational membership, team assignments, and role-based access control permissions based on SAML assertions, LDAP group memberships, or OAuth claims"
# Gets truncated with "..." - loses important information
```

**✅ Better (concise, under 200 chars):**
```python
resource_purpose = "attribute mapping rules for mapping users to organizations or teams based on external attributes"
```

**❌ Not LLM friendly (buries key information after 180 chars):**
```python
resource_purpose = "configuration objects used internally by the system's HTTP routing layer and primarily consumed by the proxy service for managing network traffic distribution. These define listener ports"
# Key term "listener ports" appears too late; LLMs weight early tokens more heavily
```

**✅ Better (key terms first):**
```python
resource_purpose = "HTTP listener ports for routing incoming traffic to backend services"
```

## When to Use Each Approach

### Use `@extend_schema_if_available` with explicit `x-ai-description` when:
- ✅ You have custom actions beyond CRUD
- ✅ An operation needs unique context different from the resource purpose
- ✅ You need fine-grained control over the description

### Use `resource_purpose` when:
- ✅ The resource is **domain-specific** or uses technical jargon (e.g., "RBAC role templates", "JWT signing keys", "authentication providers")
- ✅ The resource purpose isn't immediately obvious from its name (e.g., "authenticator maps" → "attribute mapping rules")
- ✅ The resource needs contextual explanation for MCP tool selection (e.g., "audit trail entries for tracking system changes")
- ✅ You have standard CRUD operations that all share the same core purpose

### Prefer auto-generation (no resource_purpose) when:
- ✅ The resource is **self-explanatory** (e.g., "teams", "users", "organizations")
- ✅ The resource name clearly conveys its purpose
- ✅ No domain-specific context is needed for MCP tool selection

**Philosophy:** `resource_purpose` should be used when the auto-generated description would be insufficient for AI tool selection.
Docstrings serve human developers; `resource_purpose` serves AI tool selection. Most simple CRUD resources don't need
`resource_purpose` because their names are self-explanatory; however, domain-specific or technical resources, (such 
as authenticator maps, role definitions, audit trail entries, etc.) should include `resource_purpose` to provide the necessary
context for MCP tool selection.

## Opting Out

If you need to disable automatic x-ai-description generation for a specific ViewSet/APIView, set the
`skip_ai_description` field on the ViewSet, as seen below:

```python
class MyCustomViewSet(ModelViewSet):
    skip_ai_description = True
    queryset = MyModel.objects.all()
    serializer_class = MySerializer
```

## Separation of Concerns

**Docstrings are for human developers** - they can be detailed and conversational

**resource_purpose is for AI/MCP tool selection** - it should be concise and optimized for tool selection

[See examples of when to use each](#docstrings-vs-resource_purpose)

This separation ensures:
- ✅ Docstrings can be detailed and conversational for developers
- ✅ resource_purpose stays concise and optimized for AI tool selection
- ✅ Each serves its intended audience without compromise

## Examples

### Using resource_purpose

Basic examples with `resource_purpose` field:

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

### Using `@extend_schema_if_available`

Example with explicit `x-ai-description`:

```python
from ansible_base.lib.utils.schema import extend_schema_if_available

@extend_schema_if_available(extensions={"x-ai-description": "Retrieves details regarding the currently authenticated user"})
class MeViewSet(viewsets.ReadOnlyModelViewSet, AnsibleBaseView):
    model = User
    serializer_class = UserSerializer
    ...
```

### Combining Both Approaches

Using `resource_purpose` for CRUD operations and `@extend_schema_if_available` for custom actions:

```python
from rest_framework.decorators import action

from ansible_base.lib.utils.schema import extend_schema_if_available

class AuthenticatorViewSet(ModelViewSet):
    """API endpoint for authenticators."""

    # Handles list, create, retrieve, update, delete automatically
    resource_purpose = "authentication providers for configuring user login methods (LDAP, SAML, OAuth)"

    queryset = Authenticator.objects.all()
    serializer_class = AuthenticatorSerializer

    # Custom action needs explicit description
    @extend_schema_if_available(
        extensions={'x-ai-description': 'Test authenticator connection and validate configuration'}
    )
    @action(detail=True, methods=['post'])
    def test(self, request, pk=None):
        """Test authenticator connectivity"""
        ...
```

### Docstrings vs resource_purpose

Demonstrating the separation of concerns:

```python
class TeamViewSet(ModelViewSet):
    """
    API endpoint for managing teams.

    Teams organize users and control group-based permissions.
    """
    queryset = Team.objects.all()
    serializer_class = TeamSerializer
```

```python
class AuthenticatorMapViewSet(ModelViewSet):
    """API endpoint for authenticator maps."""

    resource_purpose = "attribute mapping rules for mapping external user attributes to AAP user fields"

    queryset = AuthenticatorMap.objects.all()
    serializer_class = AuthenticatorMapSerializer
```

### Auto-generated Descriptions

For self-explanatory resources, no `resource_purpose` is needed:

```python
class UserViewSet(ModelViewSet):
    """API endpoint for users."""

    queryset = User.objects.all()
    serializer_class = UserSerializer
    # Auto-generates: "List users", "Create a user", "Retrieve a user", etc.
```

```python
class OrganizationViewSet(ModelViewSet):
    """API endpoint for organizations."""

    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer
    # Auto-generates: "List organizations", "Create an organization", etc.
```

## Testing Your Descriptions

After adding or updating `resource_purpose` fields:

1. **Generate the OpenAPI schema** using your application's schema generation method
2. **Inspect the x-ai-description fields** in the generated schema

Example using `jq` to extract all x-ai-description fields:

```bash
# If schema is available as JSON file
jq '.. | ."x-ai-description"? // empty' schema.json

# Or extract specific operations
jq '.paths[][] | select(."x-ai-description") | ."x-ai-description"' schema.json
```

Example using Python:

```python
import json

with open('schema.json') as f:
    schema = json.load(f)

# Find all x-ai-description fields
for path, operations in schema.get('paths', {}).items():
    for method, operation in operations.items():
        if isinstance(operation, dict) and 'x-ai-description' in operation:
            print(f"{method.upper()} {path}")
            print(f"  {operation['x-ai-description']}\n")
```

3. **Verify descriptions:**
   - Are clear and explain WHAT and WHY
   - Stay under 200 characters (preferred) or 300 characters (maximum)
   - Provide useful context for MCP tool selection

## Enabling Automatic x-ai-description Generation

Automatic `x-ai-description` generation should be enabled by default, as they are defined in the `DEFAULT_SPECTACULAR_SETTINGS`
dynamic settings. If you have explicit `PREPROCESSING_HOOKS` or `POSTPROCESSING_HOOKS` defined in your Django settings, then
these hooks will need to be explicitly registered using the following step.

### Configuration

Include the `SPECTACULAR_SETTINGS` dictionary in your Django settings file:

**NOTE:** Again, this is only needed if you are already defining these values. If these are undefined, then no additional
configuration is required.

```python
SPECTACULAR_SETTINGS = {
    # ... your existing settings ...

    'PREPROCESSING_HOOKS': [
        ...,
        'ansible_base.api_documentation.preprocessing_hooks.collect_ai_description_metadata',
    ],
    'POSTPROCESSING_HOOKS': [
        ...,
        'ansible_base.api_documentation.postprocessing_hooks.add_x_ai_description',
    ],
}
```
