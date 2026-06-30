import json

from django.urls import reverse
from oauth2_provider.views.oidc import ConnectDiscoveryInfoView


class DiscoveryInfoView(ConnectDiscoveryInfoView):
    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)

        if response.status_code != 200:
            return response

        data = json.loads(response.content)
        # Uses build_absolute_uri() consistent with how the parent ConnectDiscoveryInfoView
        # builds authorization_endpoint, token_endpoint, etc. Host header injection is
        # mitigated by Django's ALLOWED_HOSTS (enforced when DEBUG=False).
        data["revocation_endpoint"] = request.build_absolute_uri(reverse("oauth2_provider:revoke-token"))
        # should be removed once DAB upgrades from django-oauth-toolkit 2.3.0 to >=2.4.0,
        # which adds code_challenge_methods_supported to ConnectDiscoveryInfoView natively.
        data["code_challenge_methods_supported"] = ["S256", "plain"]

        response.content = json.dumps(data)
        return response
