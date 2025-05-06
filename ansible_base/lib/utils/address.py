import enum
import ipaddress
import re


class AddressType(enum.Enum):
    HOSTNAME = "hostname"
    IPv4 = "ipv4"
    IPv6 = "ipv6"
    UNKNOWN = "unknown"


def _classify_address_string(address_string) -> AddressType:
    """
    Categorizes a given string as IPv4, IPv6, hostname, or unknown.

    Args:
        address_string: The string to categorize.

    Returns:
        A value of AddressType indicating the category.
    """
    try:
        ipaddress.IPv4Address(address_string)
        return AddressType.IPv4
    except ipaddress.AddressValueError:
        pass

    try:
        ipaddress.IPv6Address(address_string)
        return AddressType.IPv6
    except ipaddress.AddressValueError:
        pass

    # Basic hostname check (can be expanded for more rigorous validation)
    if re.match(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?" r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$", address_string):
        return AddressType.HOSTNAME

    return AddressType.UNKNOWN


def classify_address_string(address_string) -> AddressType:
    """
    Categorizes a given string as IPv4, IPv6, hostname, or unknown.

    An IPv6 address wrapped in [] is considered a hostname.

    Args:
        address_string: The string to categorize.

    Returns:
        A value of AddressType indicating the category.
    """
    address_type = _classify_address_string(address_string)
    if address_type != AddressType.UNKNOWN:
        return address_type

    # We could be dealing with an IPv6 address wrapped in [].
    # If that is the case we want to identify it as a host name.
    if (address_string[0] == "[") and (address_string[-1] == "]"):
        address_type = _classify_address_string(address_string[1:-1])

        # Only an address type of IPv6 is considered valid here.
        # We don't want to treat any other specification as valid.
        if address_type == AddressType.IPv6:
            return AddressType.HOSTNAME

    return AddressType.UNKNOWN


def classify_and_split_address_string(address_string) -> tuple[AddressType, str, str]:
    """
    Categorizes a given string with optional ":<port>" suffix as IPv4, IPv6,
    hostname, or unknown.

    Args:
        address_string: The string to categorize.

    Returns:
        A tuple of the form (AddressType, address string, port string) where
        address_string and port_string are only valid (though port string may
        be an empty string) when AddressType is not AddressType.UNKNOWN.
    """
    address_type = classify_address_string(address_string)
    if address_type != AddressType.UNKNOWN:
        # A known type with no port.
        return (address_type, address_string, "")

    # Split into potential address and port and classify the address.
    (address_string, _, port) = address_string.rpartition(":")
    address_type = classify_address_string(address_string)
    if address_type != AddressType.UNKNOWN:
        # A known type with a port.
        return (address_type, address_string, port)

    # An unknown address type.
    return (AddressType.UNKNOWN, "", "")


def is_hostname_address_string(address_string: str) -> bool:
    return classify_address_string(address_string) == AddressType.HOSTNAME


def is_ipv4_address_string(address_string: str) -> bool:
    return classify_address_string(address_string) == AddressType.IPv4


def is_ipv6_address_string(address_string: str) -> bool:
    return classify_address_string(address_string) == AddressType.IPv6
