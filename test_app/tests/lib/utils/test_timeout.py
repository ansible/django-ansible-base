from time import sleep

import pytest

from ansible_base.lib.utils.timeout import Timeout


def test_timeout_success():
    with Timeout(10):
        print("Working")


def test_timeout_timeout():
    with pytest.raises(Timeout.TimeoutException):
        with Timeout(1):
            sleep(2)
