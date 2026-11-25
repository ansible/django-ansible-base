"""FIPS compatibility for protocol-mandated MD5 usage.

The RADIUS (RFC 2865) and TACACS+ (RFC 8907) protocols both require MD5
in their packet formats: RADIUS uses it for the request/response
authenticators and for hiding the User-Password attribute, while TACACS+
uses it to obfuscate the packet body. The third-party client libraries
used by the RADIUS and TACACS+ authenticator plugins (pyrad and
tacacs_plus) invoke ``hashlib.md5()`` without ``usedforsecurity=False``,
which raises ``ValueError`` on FIPS-enabled systems where the system
crypto policy disables MD5.

The MD5 usage in those libraries is mandated by the protocol
specifications and is not a cryptographic decision made by this
application, so it qualifies as non-security usage of MD5. This module
patches the libraries to request MD5 with ``usedforsecurity=False``,
which RHEL's OpenSSL permits even in FIPS mode.

The patch is a no-op on systems where MD5 is available.
"""

import hashlib
import logging

logger = logging.getLogger("ansible_base.authentication.utils.fips_compat")

__all__ = ["enable_protocol_md5"]


def _fips_md5(*args, **kwargs):
    """Wrap ``hashlib.md5`` requesting non-security usage of MD5."""
    kwargs.setdefault("usedforsecurity", False)
    return hashlib.md5(*args, **kwargs)


class _HashlibModuleProxy:
    """Proxy standing in for the hashlib module inside patched libraries.

    pyrad 2.5+ calls ``hashlib.md5`` through its module-level ``hashlib``
    reference, so the reference is swapped for this proxy.
    """

    def __getattr__(self, name):
        return getattr(hashlib, name)

    @staticmethod
    def md5(*args, **kwargs):
        kwargs.setdefault("usedforsecurity", False)
        return hashlib.md5(*args, **kwargs)


def _md5_unavailable() -> bool:
    """Check whether plain ``hashlib.md5`` is rejected (FIPS enforced)."""
    try:
        hashlib.md5(b"")
    except ValueError:
        return True
    return False


def enable_protocol_md5() -> None:
    """Allow protocol-mandated MD5 in pyrad and tacacs_plus under FIPS.

    Safe to call on any system: the libraries are only patched when
    plain ``hashlib.md5`` is unavailable, i.e. when FIPS is enforced.
    """
    if not _md5_unavailable():
        return

    logger.info("MD5 is unavailable (FIPS mode); patching pyrad and tacacs_plus for protocol-mandated MD5 usage")

    try:
        import pyrad.client
        import pyrad.packet

        # pyrad >= 2.5 calls hashlib.md5 directly on its packet and client
        # modules; swap the module reference for a proxy that flags the
        # usage as non-security related.
        pyrad.packet.hashlib = _HashlibModuleProxy()
        pyrad.client.hashlib = _HashlibModuleProxy()
        # pyrad 2.4 (shipped in AAP RPMs) binds hashlib.md5 to a module
        # level alias at import time.
        if hasattr(pyrad.packet, "md5_constructor"):
            pyrad.packet.md5_constructor = _fips_md5
    except ImportError:
        logger.warning("pyrad is not installed, skipping FIPS MD5 compatibility patch")

    try:
        import tacacs_plus.client
        import tacacs_plus.packet

        # tacacs_plus does "from hashlib import md5" on both modules, so
        # the bound name must be replaced on each module.
        tacacs_plus.packet.md5 = _fips_md5
        tacacs_plus.client.md5 = _fips_md5
    except ImportError:
        logger.warning("tacacs_plus is not installed, skipping FIPS MD5 compatibility patch")
