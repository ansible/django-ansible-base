import pytest

from ansible_base.lib.utils.address import (
    AddressType,
    classify_address_string,
    classify_and_split_address_string,
    is_hostname_address_string,
    is_ipv4_address_string,
    is_ipv6_address_string,
)


@pytest.mark.parametrize(
    "address,expected",
    [
        ("127.0.0.1", AddressType.IPv4),
        ("[127.0.0.1]", AddressType.UNKNOWN),
        ("10.0.1.1", AddressType.IPv4),
        ("[10.0.1.1]", AddressType.UNKNOWN),
        ("::1", AddressType.IPv6),
        ("[::1]", AddressType.HOSTNAME),
        ("2600:1f18:218b:5902:e5d4:54de:fdc1:24b8", AddressType.IPv6),
        ("[2600:1f18:218b:5902:e5d4:54de:fdc1:24b8]", AddressType.HOSTNAME),
        ("localhost", AddressType.HOSTNAME),
        ("[localhost]", AddressType.UNKNOWN),
        ("a-host-name", AddressType.HOSTNAME),
        ("[a-host-name]", AddressType.UNKNOWN),
    ],
)
def test_classify_address(address, expected):
    assert classify_address_string(address) == expected


@pytest.mark.parametrize(
    "address,expected",
    [
        ("127.0.0.1", (AddressType.IPv4, "127.0.0.1", "")),
        ("127.0.0.1:1234", (AddressType.IPv4, "127.0.0.1", "1234")),
        ("10.0.1.1:1234", (AddressType.IPv4, "10.0.1.1", "1234")),
        ("::1", (AddressType.IPv6, "::1", "")),
        ("[::1]:1234", (AddressType.HOSTNAME, "[::1]", "1234")),
        ("2600:1f18:218b:5902:e5d4:54de:fdc1:24b8", (AddressType.IPv6, "2600:1f18:218b:5902:e5d4:54de:fdc1:24b8", "")),
        ("2600:1f18:218b:5902:e5d4:54de:fdc1:24b8:1234", (AddressType.IPv6, "2600:1f18:218b:5902:e5d4:54de:fdc1:24b8", "1234")),
        ("[2600:1f18:218b:5902:e5d4:54de:fdc1:24b8]", (AddressType.HOSTNAME, "[2600:1f18:218b:5902:e5d4:54de:fdc1:24b8]", "")),
        ("[2600:1f18:218b:5902:e5d4:54de:fdc1:24b8]:1234", (AddressType.HOSTNAME, "[2600:1f18:218b:5902:e5d4:54de:fdc1:24b8]", "1234")),
        ("localhost", (AddressType.HOSTNAME, "localhost", "")),
        ("localhost:1234", (AddressType.HOSTNAME, "localhost", "1234")),
        ("a-host-name", (AddressType.HOSTNAME, "a-host-name", "")),
        ("a-host-name:1234", (AddressType.HOSTNAME, "a-host-name", "1234")),
    ],
)
def test_classify_and_split_address(address, expected):
    assert classify_and_split_address_string(address) == expected


@pytest.mark.parametrize(
    "address",
    [
        "localhost",
        "a-host-name",
        "[2600:1f18:218b:5902:e5d4:54de:fdc1:24b8]",
    ],
)
def test_is_hostname_address(address):
    assert is_hostname_address_string(address)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.1.1",
    ],
)
def test_is_ipv4_address(address):
    assert is_ipv4_address_string(address)


@pytest.mark.parametrize(
    "address",
    [
        "::1",
        "2600:1f18:218b:5902:e5d4:54de:fdc1:24b8",
    ],
)
def test_is_ipv6_address(address):
    assert is_ipv6_address_string(address)
