import pytest

from oauth2_provider.urls import oidc_urlpatterns as dot_oidc_urlpatterns
from ansible_base.oauth2_provider.urls import oauth_urls

dot_oidc_names = {p.name for p in dot_oidc_urlpatterns}
dab_oidc_names = {
    getattr(p, 'name', None) for p in oauth_urls
} & dot_oidc_names

@pytest.mark.parametrize("name", sorted(dab_oidc_names))
def test_oidc_url_patterns_match_dot(name):
    """Ensure our OIDC URL patterns stay aligned with the pinned DOT version."""
    dot_pattern = next(p for p in dot_oidc_urlpatterns if p.name == name)
    dab_pattern = next(p for p in oauth_urls if getattr(p, 'name', None) == name)
    assert dab_pattern.pattern._regex == dot_pattern.pattern._regex, (
        f"URL pattern for '{name}' differs from django-oauth-toolkit. "
        f"DAB: {dab_pattern.pattern._regex}, DOT: {dot_pattern.pattern._regex}"
    )
