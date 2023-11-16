import base64
import hashlib

from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from django.conf import settings
from django.utils.encoding import smart_bytes, smart_str

__all__ = [
    'ENCRYPTED_STRING',
    'ansible_encryption',
]


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
        value = self.decrypt(encrypted)

        return smart_str(value)


ansible_encryption = Fernet256()
