"""
Workload Identity module.

Provides scope definitions and registry for workload identity tokens.
"""

from .base import BaseWorkloadIdentityScope
from .controller import AutomationControllerJobScope

SCOPE_REGISTRY = {
    AutomationControllerJobScope.name: AutomationControllerJobScope,
}

__all__ = [
    'BaseWorkloadIdentityScope',
    'AutomationControllerJobScope',
    'SCOPE_REGISTRY',
]
