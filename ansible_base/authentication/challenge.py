"""Shared DRF authentication challenge behavior."""

from typing import Any

from ansible_base.lib.utils.auth import get_authentication_challenge, record_authentication_challenge


class ChallengeAwareAuthenticationMixin:
    """Resolve the first safe challenge recorded while authenticating a request."""

    def record_authentication_challenge(self, request: Any, challenge: str) -> None:
        record_authentication_challenge(request, challenge)

    def get_default_authentication_challenge(self, _request: Any) -> str | None:
        return None

    def authenticate_header(self, request: Any) -> str | None:
        challenge = get_authentication_challenge(request)
        if challenge is not None:
            return challenge
        return self.get_default_authentication_challenge(request)
