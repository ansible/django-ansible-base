"""Integration: generated OpenAPI includes CleanText pattern components."""


def test_openapi_schema_includes_clean_text_pattern_components(admin_api_client):
    response = admin_api_client.get('/api/v1/docs/schema/')
    assert response.status_code == 200
    schemas = response.data['components']['schemas']
    assert 'CleanTextFieldInfo' in schemas
    assert 'CleanTextNestedStringField' in schemas
    assert 'AuthenticatorPluginConfigurationField' in schemas

    field_info = schemas['CleanTextFieldInfo']['properties']
    for key in ('pattern', 'patternDescription', 'flags', 'normalize'):
        assert key in field_info
        assert key not in schemas['CleanTextFieldInfo'].get('required', [])

    nested = schemas['CleanTextNestedStringField']['properties']
    assert 'patternDescription' in nested
    assert 'pattern_description' not in nested
