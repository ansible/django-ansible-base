import dataclasses
import enum
import ipaddress
import re


class AddressType(enum.Enum):
    """
    AddressType provides an abstracted identification of the determined kind of
    an address.  The abstraction eliminates cohesion between the provided
    address identification functionality and its clients.

    The type allows a client which may be configured with any of the supported
    types to identify which type was specified and perform necessary runtime
    handling.

    An example would be a client which uses the values from its configuration
    to construct URLs and which is configured using raw IPv6 addreesses. The
    client needs to be able to determine the address type to know what
    processing (such as enclosing IPv6 addresses in []s) is needed to
    successfully utilize it.
    """

    HOSTNAME = "hostname"
    IPv4 = "ipv4"
    IPv6 = "ipv6"
    UNKNOWN = "unknown"


@dataclasses.dataclass(frozen=True)
class AddressTypeResponse(object):
    """
    AddressTypeResponse is returned from the classify address method describing
    the detected address including splitting it into address and port parts as
    appicable.

    Strings are used for the address and port so as to minimize changes to
    existing code to facilitate use of the classification functionality
    provided.  An empty string indicates the non-existence of that particular
    attribute as part of the classified address.

    The address and port fields are not valid in any sense if the type field is
    AddressType.UNKNOWN.
    """

    type: AddressType
    address: str = ""
    port: str = ""


def _classify_base_address(address: str) -> AddressType:
    """
    Categorizes a given string as IPv4, IPv6, hostname, or unknown.

    Args:
        address: The string to categorize.

    Returns:
        A value of AddressType indicating the category.
    """
    try:
        ipaddress.IPv4Address(address)
        return AddressType.IPv4
    except ipaddress.AddressValueError:
        pass

    try:
        ipaddress.IPv6Address(address)
        return AddressType.IPv6
    except ipaddress.AddressValueError:
        pass

    # Basic hostname check (can be expanded for more rigorous validation)
    # The original regex was generated via Gemini AI.
    # It was modified to require the first character be alphabetic to eliminate
    # a string composed of nothing but digits be recognized as a hostname.
    if re.match(r"^[a-zA-Z](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$", address):
        return AddressType.HOSTNAME

    return AddressType.UNKNOWN


def _classify_address(address: str) -> AddressType:
    """
    Categorizes a given string as IPv4, IPv6, hostname, or unknown.

    An IPv6 address wrapped in [] is considered a hostname.

    Args:
        address: The string to categorize.

    Returns:
        A value of AddressType indicating the category.
    """
    # We could be dealing with an IPv6 address wrapped in [].
    # If that is the case we want to identify it as a host name.
    # The reason for this is the common use case where an IPv6 in []s is
    # utilized in the same manner as a hostname.  Thus we eliminate special
    # casing on the part of the client to only the situation where they have a
    # "raw" IPv6 address.

    # Check that the address is at least two characters long.
    if (len(address) >= 2) and (address[0] == "[") and (address[-1] == "]"):
        address_type = _classify_base_address(address[1:-1])

        # Only an address type of IPv6 is considered valid here.
        # We don't want to treat any other specification as valid.
        if address_type == AddressType.IPv6:
            return AddressType.HOSTNAME
        return AddressType.UNKNOWN

    return _classify_base_address(address)


def classify_address(address: str) -> AddressTypeResponse:
    """
    Categorizes a given string with optional ":<port>" suffix as IPv4, IPv6,
    hostname, or unknown.

    Args:
        address: The string to categorize.

    Returns:
        An instance of AddressTypeResponse.
    """
    address_type = _classify_address(address)
    if address_type != AddressType.UNKNOWN:
        # A known type with no port.
        return AddressTypeResponse(address_type, address)

    # Split into potential address and port and classify the address.
    (address, _, port) = address.rpartition(":")
    address_type = _classify_address(address)
    if address_type != AddressType.UNKNOWN:
        # A known type with a port.
        return AddressTypeResponse(address_type, address, port)

    # An unknown address type.
    return AddressTypeResponse(AddressType.UNKNOWN)
