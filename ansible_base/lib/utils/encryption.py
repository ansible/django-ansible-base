import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from django.conf import settings
from django.utils.encoding import force_bytes, smart_bytes, smart_str
from django.utils.functional import SimpleLazyObject

__all__ = [
    'ENCRYPTED_STRING',
    'ansible_encryption',
    'generate_hmac_sha256_shared_secret',
    'validate_hmac_sha256_shared_secret',
]

logger = logging.getLogger('ansible_base.lib.utils.encryption')


ENCRYPTED_STRING = '$encrypted$'
ENCRYPTION_METHOD = 'AESCBC'


class Fernet256(Fernet):
    """Not technically Fernet, but uses the base of the Fernet spec and uses AES-256-CBC
    instead of AES-128-CBC. All other functionality remain identical.
    """

    def __init__(self):
        h = hashlib.sha512()
        h.update(smart_bytes(settings.SECRET_KEY))
        self.key = h.digest()

        if len(self.key) != 64:
            raise ValueError("Fernet key must be 64 url-safe base64-encoded bytes.")

        self._signing_key = self.key[:32]
        self._encryption_key = self.key[32:]
        self._backend = default_backend()

    def encrypt_string(self, value: str) -> str:
        # Its possible for a serializer to accept a number for a CharField (like 5). In the serializer its "5" but when we get here it might be 5
        if type(value) is not str:
            value = str(value)

        if value.startswith(ENCRYPTED_STRING):
            return value
        encrypted = self.encrypt(smart_bytes(value))
        b64data = smart_str(base64.b64encode(encrypted))
        return f'{ENCRYPTED_STRING}UTF8${ENCRYPTION_METHOD}${b64data}'

    def decrypt_string(self, value: str) -> str:
        if type(value) is not str:
            raise ValueError("decrypt_string can only accept string")

        if not value.startswith(ENCRYPTED_STRING):
            return value

        raw_data = value[len(ENCRYPTED_STRING) :]

        # If the encrypted string contains a UTF8 marker, discard it
        if raw_data.startswith('UTF8$'):
            raw_data = raw_data[len('UTF8$') :]

        # Extract the algorithm and ensure its what we expect
        algo, b64data = raw_data.split('$', 1)
        if algo != ENCRYPTION_METHOD:
            raise ValueError(f'Unsupported algorithm: {algo}')

        # Finally decode the value
        encrypted = base64.b64decode(b64data)

        return smart_str(self.decrypt(encrypted))


ansible_encryption = SimpleLazyObject(func=lambda: Fernet256())


class SharedSecretNotFound(Exception):
    pass


def generate_hmac_sha256_shared_secret(nonce: Optional[str] = None) -> str:
    shared_secret = getattr(settings, 'ANSIBLE_BASE_SHARED_SECRET', None)
    if shared_secret is None or not shared_secret:
        logger.error("The setting ANSIBLE_BASE_SHARED_SECRET was not set, insecurely using default")
        raise SharedSecretNotFound()

    if nonce is None:
        nonce = str(time.time())

    message = {'nonce': nonce, 'shared_secret': shared_secret}
    signature = hmac.new(force_bytes(shared_secret), msg=force_bytes(json.dumps(message)), digestmod='sha256').hexdigest()
    secret = f"{nonce}:{signature}"

    return secret


def validate_hmac_sha256_shared_secret(secret: str) -> bool:
    nonce, _signature = secret.split(':')
    expected_secret = generate_hmac_sha256_shared_secret(nonce=nonce)

    return expected_secret == secret
