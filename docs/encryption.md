# Encryption

django-ansible-base has a built in method for encrypting and decryption of strings as well as a constant which can be displayed in an API to indicate that a string is encrypted.

These come from `ansible_base.common.utils.encryption` like:

```
from ansible_base.common.utils.encryption import ENCRYPTED_STRING, ansible_encryption
```

You could then have code like:
```
        if type(instance.value) is str and instance.value.startswith(ENCRYPTED_STRING):
            instance.value = ansible_encryption.decrypt_string(instance.value)
```

For encrypting a string you can use the `encrypt` method of `ansible_encryption` like:
```
ansible_encryption.encrypt_string(string_value)
```
