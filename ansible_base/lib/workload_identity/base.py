"""
Base class for OIDC workload identity scopes.
"""

from abc import abstractmethod


class BaseWorkloadIdentityScope:
    """
    Base class for OIDC workload identity scopes.
    """

    SERVICE_TYPE_CONTROLLER = "controller"
    SERVICE_TYPE_EDA = "eda"
    SERVICE_TYPE_HUB = "hub"
    SERVICE_TYPE_GATEWAY = "gateway"

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
    @abstractmethod
    def get_target_claim_names_to_sub_stubs(cls) -> dict[str, str]:
        """
        Return a mapping of claim names to their corresponding sub claim stubs.

        :return: A dictionary mapping claim names to sub claim stubs.
        :rtype: dict[str, str]
        """
        raise NotImplementedError("Subclasses must implement get_target_claim_names_to_sub_stubs()")

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

    @classmethod
    def is_service_allowed(cls, service_name: str) -> bool:
        """
        Check if a service is authorized to request this scope.

        Subclasses MUST override this method to authorize specific services.
        The default implementation returns False (deny all services).

        :param service_name: The name of the service requesting the scope.
        :type service_name: str
        :return: True if the service is allowed, False otherwise.
        :rtype: bool
        """
        return False

    @classmethod
    def generate_sub_claim(cls, workload_claims: dict) -> str:
        """
        Generate a sub claim string from workload claims using the scope's claim mapping.

        Given a dictionary with the claims of a workload, generates a sub claim string with the following format:
        "job:<job_name>:organization:<organization_name>:project:<project_name>:job_template:<job_template_name>"

        Note: The specified claim names are included in the output sub claim value even if they
        are empty. Claim validation is expected to take care of doing these checks before this
        function is called.

        :param workload_claims: A dictionary containing the workload claims (claim names to values)
        :type workload_claims: dict
        :return: A string containing the sub claim
        :rtype: str
        """
        target_claim_names_to_sub_stubs = cls.get_target_claim_names_to_sub_stubs()
        return ":".join([f"{target_claim_names_to_sub_stubs[key]}:{workload_claims.get(key, '')}" for key in target_claim_names_to_sub_stubs.keys()])
