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

    @abstractmethod
    def populate_claims(self, workload_data: dict) -> dict:
        """
        Populate claims based on the provided workload data.

        :param workload_data: The workload_data dictionary used to populate claim values.
                        This workload_data identifies the AAP workload that is requesting a scope.
        :type workload_data: dict
        :return: A dictionary mapping claim names to their corresponding values generated from the workload_data.
        :rtype: dict
        """
        raise NotImplementedError("Subclasses will implement populate_claims() in future iterations")
