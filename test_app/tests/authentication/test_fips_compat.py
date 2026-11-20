import sys
from unittest import mock

from ansible_base.authentication.utils import fips_compat


def _capture_library_references() -> dict:
    """Capture the library module attributes modified by enable_protocol_md5."""
    import pyrad.client
    import pyrad.packet
    import tacacs_plus.client
    import tacacs_plus.packet

    refs = {
        "pyrad_packet_hashlib": pyrad.packet.hashlib,
        "pyrad_client_hashlib": pyrad.client.hashlib,
        "tacacs_packet_md5": tacacs_plus.packet.md5,
        "tacacs_client_md5": tacacs_plus.client.md5,
    }
    # Only pyrad 2.4 (shipped in AAP RPMs) binds hashlib.md5 to this alias.
    if hasattr(pyrad.packet, "md5_constructor"):
        refs["pyrad_packet_md5_constructor"] = pyrad.packet.md5_constructor
    return refs


def _restore_library_references(refs: dict) -> None:
    """Restore the exact library references captured before patching."""
    import pyrad.client
    import pyrad.packet
    import tacacs_plus.client
    import tacacs_plus.packet

    pyrad.packet.hashlib = refs["pyrad_packet_hashlib"]
    pyrad.client.hashlib = refs["pyrad_client_hashlib"]
    tacacs_plus.packet.md5 = refs["tacacs_packet_md5"]
    tacacs_plus.client.md5 = refs["tacacs_client_md5"]
    if "pyrad_packet_md5_constructor" in refs:
        pyrad.packet.md5_constructor = refs["pyrad_packet_md5_constructor"]


def test_md5_unavailable_detects_availability():
    """_md5_unavailable reports whether plain hashlib.md5 is rejected."""
    import hashlib

    with mock.patch.object(hashlib, "md5", side_effect=ValueError("disabled for FIPS")):
        assert fips_compat._md5_unavailable() is True
    with mock.patch.object(hashlib, "md5", return_value=None):
        assert fips_compat._md5_unavailable() is False


def test_enable_protocol_md5_is_noop_when_md5_available():
    """On non-FIPS systems no library attributes are patched."""
    with mock.patch.object(fips_compat, "_md5_unavailable", return_value=False):
        with mock.patch.object(fips_compat, "_HashlibModuleProxy") as proxy:
            fips_compat.enable_protocol_md5()
    proxy.assert_not_called()


def test_enable_protocol_md5_patches_libraries_when_md5_unavailable():
    """When plain hashlib.md5 is rejected, pyrad and tacacs_plus are patched.

    A ValueError from hashlib.md5 simulates FIPS enforcement. After the
    patch, the libraries must call hashlib.md5 with
    usedforsecurity=False, which the (still simulated) FIPS system
    accepts.
    """
    import hashlib

    import pyrad.client
    import pyrad.packet
    import tacacs_plus.client
    import tacacs_plus.packet

    original_refs = _capture_library_references()
    real_md5 = hashlib.md5

    calls = []

    def fips_md5(data=b"", *, usedforsecurity=True):
        calls.append(usedforsecurity)
        if usedforsecurity:
            raise ValueError("[digital envelope routines]: unsupported")
        return real_md5(data, usedforsecurity=False)

    try:
        with mock.patch.object(hashlib, "md5", fips_md5):
            fips_compat.enable_protocol_md5()

            # pyrad >= 2.5 style module reference
            assert isinstance(pyrad.packet.hashlib, fips_compat._HashlibModuleProxy)
            assert isinstance(pyrad.client.hashlib, fips_compat._HashlibModuleProxy)
            # pyrad 2.4 style module level alias
            if "pyrad_packet_md5_constructor" in original_refs:
                assert pyrad.packet.md5_constructor is fips_compat._fips_md5
            # tacacs_plus bound names
            assert tacacs_plus.packet.md5 is fips_compat._fips_md5
            assert tacacs_plus.client.md5 is fips_compat._fips_md5

            # The patched call paths must succeed with non-security MD5.
            assert pyrad.packet.hashlib.md5(b"secret").digest()
            assert tacacs_plus.packet.md5(b"secret").digest()
            if "pyrad_packet_md5_constructor" in original_refs:
                assert pyrad.packet.md5_constructor(b"secret").digest()
        # The first recorded call is the availability probe performed with
        # plain (security) usage; every later call comes from the patched
        # libraries and must request non-security usage.
        assert calls[0] is True
        assert all(flag is False for flag in calls[1:])
    finally:
        _restore_library_references(original_refs)


def test_enable_protocol_md5_skips_missing_libraries():
    """A missing pyrad or tacacs_plus is logged and skipped, not raised."""
    with mock.patch.dict(
        sys.modules,
        {
            "pyrad": None,
            "pyrad.client": None,
            "pyrad.packet": None,
            "tacacs_plus": None,
            "tacacs_plus.client": None,
            "tacacs_plus.packet": None,
        },
    ):
        with mock.patch.object(fips_compat, "_md5_unavailable", return_value=True):
            fips_compat.enable_protocol_md5()


def test_hashlib_proxy_forwards_other_names():
    """The hashlib proxy passes through attributes other than md5."""
    import hashlib

    proxy = fips_compat._HashlibModuleProxy()
    assert proxy.sha256 is hashlib.sha256
