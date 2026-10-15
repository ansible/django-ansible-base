from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from jwt.algorithms import get_default_algorithms

# Algorithms safe for inbound bearer-token validation (asymmetric only).
# Excludes "none" and symmetric HS* to prevent algorithm-confusion attacks.
ASYMMETRIC_JWT_ALGORITHMS = sorted(name for name in get_default_algorithms().keys() if name != "none" and not name.startswith("HS"))


class JWTAlgorithmListFieldValidator:
    """Validate that every entry is in an allowed JWT algorithm set.

    Defaults to PyJWT's full algorithm set (preserves OIDC behavior).
    Pass an explicit allow-list for stricter callers such as external_oauth.
    """

    def __init__(self, allowed_values=None):
        self.allowed_values = list(allowed_values) if allowed_values is not None else list(get_default_algorithms().keys())

    def __call__(self, value):
        if not all(item in self.allowed_values for item in value):
            raise ValidationError(
                _("%(value)s contains items not in the allowed list: %(allowed_values)s"),
                params={"value": value, "allowed_values": self.allowed_values},
            )
