from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def asymmetric_jwt_algorithms():
    """Asymmetric JWT algorithms only — excludes 'none' and symmetric HS*."""
    from jwt.algorithms import get_default_algorithms

    return sorted(name for name in get_default_algorithms().keys() if name != "none" and not name.startswith("HS"))


class JWTAlgorithmListFieldValidator:
    """Validate that every entry is in an allowed JWT algorithm set.

    Defaults to PyJWT's full algorithm set (preserves OIDC behavior).
    Pass an explicit allow-list (or callable returning one) for stricter callers.
    """

    def __init__(self, allowed_values=None):
        self._allowed_values = allowed_values

    @property
    def allowed_values(self):
        if self._allowed_values is None:
            from jwt.algorithms import get_default_algorithms

            return list(get_default_algorithms().keys())
        if callable(self._allowed_values):
            return list(self._allowed_values())
        return list(self._allowed_values)

    def __call__(self, value):
        allowed = self.allowed_values
        if not all(item in allowed for item in value):
            raise ValidationError(
                _("%(value)s contains items not in the allowed list: %(allowed_values)s"),
                params={"value": value, "allowed_values": allowed},
            )
