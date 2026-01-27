import pytest

from ansible_base.lib.workload_identity.base import BaseWorkloadIdentityScope


def test_list_claims():
    """
    Test that the base Scope class raises NotImplementedError for list_claims().
    """
    scope = BaseWorkloadIdentityScope()
    with pytest.raises(NotImplementedError, match="Subclasses must implement list_claims\\(\\)"):
        scope.list_claims()


def test_populate_claims():
    """
    Test that the base Scope class raises NotImplementedError for populate_claims().
    """
    scope = BaseWorkloadIdentityScope()
    with pytest.raises(NotImplementedError, match="Subclasses will implement populate_claims\\(\\) in future iterations"):
        scope.populate_claims({})
