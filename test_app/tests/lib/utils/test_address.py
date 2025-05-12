import pytest

from ansible_base.lib.utils.address import AddressType, AddressTypeResponse, classify_address


@pytest.mark.parametrize(
    "address,expected",
    [
        ("127.0.0.1", AddressTypeResponse(AddressType.IPv4, "127.0.0.1")),
        ("[127.0.0.1]", AddressTypeResponse(AddressType.UNKNOWN, "[127.0.0.1]")),
        ("127.0.0.1:1234", AddressTypeResponse(AddressType.IPv4, "127.0.0.1", "1234")),
        ("10.0.1.1:1234", AddressTypeResponse(AddressType.IPv4, "10.0.1.1", "1234")),
        ("10.0.1.1", AddressTypeResponse(AddressType.IPv4, "10.0.1.1")),
        ("[10.0.1.1]", AddressTypeResponse(AddressType.UNKNOWN, "[10.0.1.1]")),
        ("::1", AddressTypeResponse(AddressType.IPv6, "::1")),
        ("[::1]", AddressTypeResponse(AddressType.IPv6, "::1")),
        ("[::1]:1234", AddressTypeResponse(AddressType.IPv6, "::1", "1234")),
        ("2600:1f18:218b:5902:e5d4:54de:fdc1:24b8", AddressTypeResponse(AddressType.IPv6, "2600:1f18:218b:5902:e5d4:54de:fdc1:24b8")),
        ("[2600:1f18:218b:5902:e5d4:54de:fdc1:24b8]", AddressTypeResponse(AddressType.IPv6, "2600:1f18:218b:5902:e5d4:54de:fdc1:24b8")),
        ("2600:1f18:218b:5902:e5d4:54de:fdc1:24b8:1234", AddressTypeResponse(AddressType.IPv6, "2600:1f18:218b:5902:e5d4:54de:fdc1:24b8", "1234")),
        ("[2600:1f18:218b:5902:e5d4:54de:fdc1:24b8]:1234", AddressTypeResponse(AddressType.IPv6, "2600:1f18:218b:5902:e5d4:54de:fdc1:24b8", "1234")),
        ("localhost", AddressTypeResponse(AddressType.HOSTNAME, "localhost")),
        ("[localhost]", AddressTypeResponse(AddressType.UNKNOWN, "[localhost]")),
        ("localhost:1234", AddressTypeResponse(AddressType.HOSTNAME, "localhost", "1234")),
        ("a-host-name", AddressTypeResponse(AddressType.HOSTNAME, "a-host-name")),
        ("a-host-name:1234", AddressTypeResponse(AddressType.HOSTNAME, "a-host-name", "1234")),
        ("////////////", AddressTypeResponse(AddressType.UNKNOWN, "////////////")),
        ("123123123123", AddressTypeResponse(AddressType.UNKNOWN, "123123123123")),
    ],
)
def test_classify_address(address, expected):
    response = classify_address(address)
    assert response == expected
    if response.type == AddressType.IPv6:
        assert response.ipv6_bracketed == f"[{response.address}]"
    else:
        assert response.ipv6_bracketed is None
