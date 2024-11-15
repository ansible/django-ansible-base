import hashlib

from ansible_base.lib.utils.hashing import hash_string


def hash_tokens(apps, schema_editor):
    OAuth2AccessToken = apps.get_model("dab_oauth2_provider", "OAuth2AccessToken")
    OAuth2RefreshToken = apps.get_model("dab_oauth2_provider", "OAuth2RefreshToken")
    for model in (OAuth2AccessToken, OAuth2RefreshToken):
        for token in model.objects.all():
            # Never re-hash a hashed token
            if token.token.startswith("$"):
                continue
            hashed = hash_string(token.token, hasher=hashlib.sha256, algo="sha256")
            token.token = hashed
            token.save()
