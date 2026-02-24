"""
This module tests that the OIDC url patterns defined in ansible_base.oauth2_provider
align with the OIDC url patterns in django-oauth-toolkit.

The ansible_base.oauth2_provider re-implements these URL patterns so that they can
be feature-flagged. At the time of this writing, the patterns align with the pinned version
of django-oauth-toolkit. This is necessary because we rely on internal behaviors
of django-oauth-toolkit (e.g. oidc_issuer()) that require them to match.

The tests below are a canary. When we upgrade django-oauth-toolkit, the tests will fail.
We'll then need to update our URL patterns to fix them.
"""

import pytest
from oauth2_provider import __version__ as dot_version
from oauth2_provider.urls import oidc_urlpatterns as dot_oidc_urlpatterns
from packaging.version import parse

from ansible_base.oauth2_provider.urls import oauth_urls

dot_oidc_names = {p.name for p in dot_oidc_urlpatterns}
dab_oidc_names = {getattr(p, 'name', None) for p in oauth_urls} & dot_oidc_names


if parse(dot_version) < parse("3.0.0"):
    # Prior to django-oauth-toolkit 3.0.0, the 'jwks-info' URL is incorrectly defined as
    # re_path(r"^\.well-known/jwks.json$". The unescaped '.' in jwks.json would match any
    # single character. Our implementation uses '\.', which is correct but doesn't match
    # django-oauth-toolkit in older versions, so we skip this check.
    dab_oidc_names.remove('jwks-info')


@pytest.mark.parametrize("name", sorted(dab_oidc_names))
def test_oidc_url_patterns_match_dot(name):
    """Ensure our OIDC URL patterns stay aligned with the pinned DOT version."""
    dot_pattern = next(p for p in dot_oidc_urlpatterns if p.name == name)
    dab_pattern = next(p for p in oauth_urls if getattr(p, 'name', None) == name)
    assert dab_pattern.pattern._regex == dot_pattern.pattern._regex, (
        f"URL pattern for '{name}' differs from django-oauth-toolkit. " f"DAB: {dab_pattern.pattern._regex}, DOT: {dot_pattern.pattern._regex}"
    )
