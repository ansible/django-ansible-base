import logging
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from ansible_base.jwt_consumer.common.cert import JWTCert, JWTCertException

logger = logging.getLogger('ansible_base.jwt_consumer.common.util')

_SHARED_SECRET = 'trusted_proxy'


def generate_x_trusted_proxy_header(key: str) -> str:
    private_key = serialization.load_pem_private_key(bytes(key, 'utf-8'), password=None)
    timestamp = time.time_ns()
    message = f'{_SHARED_SECRET}-{timestamp}'
    signature = private_key.sign(bytes(message, 'utf-8'), padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())
    return f"{timestamp}-{signature.hex()}"


def validate_x_trusted_proxy_header(header_value: str, ignore_cache=False) -> bool:
    try:
        cert = JWTCert()
        cert.get_decryption_key(ignore_cache=ignore_cache)
        if cert.key is None:
            raise JWTCertException(f"Failed to load cert from setting {cert.key_name}")
    except JWTCertException as e:
        logger.error(f"Failed to validate x-trusted-proxy-header, unable to load cert {e}")
        return False

    try:
        public_key = serialization.load_pem_public_key(cert.key.encode('utf-8'))
    except Exception:
        logger.exception("Failed to load public key")
        return False

    try:
        timestamp, signature = header_value.split('-', maxsplit=1)
    except ValueError:
        logger.warning("Failed to validate x-trusted-proxy-header, malformed, expected value to contain a -")
        return False

    try:
        signature_bytes = bytes.fromhex(signature)
    except ValueError:
        logger.warning("Failed to validate x-trusted-proxy-header, malformed, expected signature to well-formed base64")
        return False

    try:
        public_key.verify(
            signature_bytes,
            bytes(f'{_SHARED_SECRET}-{timestamp}', 'utf-8'),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
        return True
    except InvalidSignature:
        if ignore_cache or not cert.cached:
            return False
        return validate_x_trusted_proxy_header(header_value, ignore_cache=True)
