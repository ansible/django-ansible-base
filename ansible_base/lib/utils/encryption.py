import base64
import hashlib
import logging
import re

from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from django.conf import settings
from django.utils.encoding import smart_bytes, smart_str
from django.utils.functional import SimpleLazyObject

__all__ = [
    'ENCRYPTED_STRING',
    'ansible_encryption',
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

    def extract_data(self, raw_data: str) -> str:
        # Sequential data extract for code reuse in is_encrypted_string and decrypt_string
        raw_data = raw_data[len(ENCRYPTED_STRING) :]

        # If the encrypted string contains a UTF8 marker, discard it
        if raw_data.startswith('UTF8$'):
            raw_data = raw_data[len('UTF8$') :]

        # Extract the algorithm and ensure its what we expect
        algo, data = raw_data.split('$', 1)
        if algo != ENCRYPTION_METHOD:
            raise ValueError(f'Unsupported algorithm: {algo}')

        return data

    def is_encrypted_string(self, value: str, invalid_algo_is_fatal: bool) -> bool:
        # Ensure input is a string already encrypted by our algorithm
        # by comparing with the decrypted and re-encrypted values
        if not value.startswith(ENCRYPTED_STRING):
            return False

        try:
            data = self.extract_data(value)
        except ValueError as ve:
            # value error is raised when algorithm is unsupported
            if invalid_algo_is_fatal:
                raise ve

        # Check if data is base64 encoded
        # **important** Note: this can fail because some strings resemble base 64 encoded ones
        # **important** for instance, if user's secret is $encrypted$UTF8$AESCBC$junk, the code will break
        # use regex pattern: ^([A-Za-z0-9+/]{4})* means the string starts with 0 or more base64 groups.
        # ([A-Za-z0-9+/]{4}|[A-Za-z0-9+/]{3}=|[A-Za-z0-9+/]{2}==)$ means
        # the string ends in one of three forms: [A-Za-z0-9+/]{4}, [A-Za-z0-9+/]{3}= or [A-Za-z0-9+/]{2}==.
        reg = r'^([A-Za-z0-9+/]{4})*([A-Za-z0-9+/]{3}=|[A-Za-z0-9+/]{2}==)?$'

        return re.match(reg, data) is not None

    def encrypt_string(self, value: str) -> str:

        # Its possible for a serializer to accept a number for a CharField (like 5). In the serializer its "5" but when we get here it might be 5
        if not isinstance(value, str):
            value = str(value)

        if self.is_encrypted_string(value, invalid_algo_is_fatal=False):
            return value

        encrypted = self.encrypt(smart_bytes(value))
        b64data = smart_str(base64.b64encode(encrypted))
        return f'{ENCRYPTED_STRING}UTF8${ENCRYPTION_METHOD}${b64data}'

    def decrypt_string(self, value: str) -> str:
        if not self.is_encrypted_string(value, invalid_algo_is_fatal=True):
            return value

        b64data = self.extract_data(value)

        # Finally decode the value
        encrypted = base64.b64decode(b64data)

        return smart_str(self.decrypt(encrypted))


ansible_encryption = SimpleLazyObject(func=lambda: Fernet256())
