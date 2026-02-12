"""
Base class for OIDC workload identity scopes.
"""

from abc import abstractmethod


class BaseWorkloadIdentityScope:
    """
    Base class for OIDC workload identity scopes.
    """

    name = ""
    description = ""

    @classmethod
    @abstractmethod
    def list_claims(cls) -> list[str]:
        """
        Return a list of all claim names defined in this scope.

        :return: A list of claim name strings.
        :rtype: list[str]
        """
        raise NotImplementedError("Subclasses must implement list_claims()")

    @classmethod
    def get_target_claim_names_to_sub_stubs(cls) -> dict[str, str]:
        """
        Return a mapping of claim names to their corresponding sub claim stubs.

        :return: A dictionary mapping claim names to sub claim stubs.
        :rtype: dict[str, str]
        """
        raise NotImplementedError("Subclasses must implement get_target_claim_names_to_sub_stubs()")
