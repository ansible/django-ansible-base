"""
Base class for OIDC workload identity scopes.
"""


class Scope:
    """
    Base class for OIDC workload identity scopes.
    """

    description = ""

    def list_claims(self) -> list[str]:
        """
        Return a list of all claim names defined in this scope.
        """
        raise NotImplementedError("Subclasses must implement list_claims()")

    def populate_claims(self, context: dict) -> dict:
        """
        Populate claims from the provided context.
        """
        raise NotImplementedError("Subclasses will implement populate_claims() in future iterations")
