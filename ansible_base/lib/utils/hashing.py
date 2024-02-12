import hashlib
import json 


def hash_serializer_data(data, hasher=hashlib.sha256):
    """Given a Dict returns a hash of its JSON serialized data""" 
    metadata_json = json.dumps(data, sort_keys=True).encode("utf-8")
    return hasher(metadata_json).hexdigest()
