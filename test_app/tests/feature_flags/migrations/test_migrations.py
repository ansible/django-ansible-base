import hashlib
import os

from django.conf import settings
from django.test import TestCase


class FileHashTest(TestCase):
    FILE_TO_CHECK_PATH = os.path.join(settings.BASE_DIR, 'ansible_base', 'feature_flags', 'definitions', 'feature_flags.yaml')
    HASH_ALGORITHM = 'sha256'
    HASH_COMMENT_PREFIX = '# FileHash:'

    def _get_last_migration_file(self):
        """
        Finds the path to the last migration file in the specified Django app.
        """
        migrations_dir = os.path.join(settings.BASE_DIR, 'ansible_base', 'feature_flags', 'migrations')
        if not os.path.isdir(migrations_dir):
            raise FileNotFoundError(f"Migrations directory not found for app: {self.APP_NAME}")

        migration_files = sorted([
            f for f in os.listdir(migrations_dir)
            if f.endswith('.py') and f != '__init__.py'
        ])

        if not migration_files:
            raise FileNotFoundError(f"No migration files found in {migrations_dir}")

        return os.path.join(migrations_dir, migration_files[-1])

    def _extract_hash_from_migration(self, migration_file_path):
        """
        Extracts the expected hash from a comment in the migration file.
        Assumes the format: '# FileHash: <hash_value>'
        """
        with open(migration_file_path, 'r') as f:
            for line in f:
                if line.strip().startswith(self.HASH_COMMENT_PREFIX):
                    return line.strip().replace(self.HASH_COMMENT_PREFIX, '').strip()
        return None

    def _calculate_file_hash(self, file_path):
        """
        Calculates the hash of the given file.
        """
        hash_func = getattr(hashlib, self.HASH_ALGORITHM, None)
        if not hash_func:
            raise ValueError(f"Unsupported hash algorithm: {self.HASH_ALGORITHM}")

        hasher = hash_func()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def test_file_hash_matches_migration_comment(self):
        """
        Checks if the hash of a specified file matches the hash commented
        in the last migration file.
        """
        # 1. Get the last migration file
        try:
            last_migration_file = self._get_last_migration_file()
        except FileNotFoundError as e:
            self.fail(f"Could not find last migration file: {e}")

        # 2. Extract the expected hash from the migration file
        expected_hash = self._extract_hash_from_migration(last_migration_file)
        self.assertIsNotNone(expected_hash,
                             f"No hash comment '{self.HASH_COMMENT_PREFIX}' found in {last_migration_file}")
        self.assertTrue(expected_hash, "Extracted hash is empty.")

        # 3. Calculate the hash of the target file
        self.assertTrue(os.path.exists(self.FILE_TO_CHECK_PATH),
                        f"File to check does not exist: {self.FILE_TO_CHECK_PATH}")
        actual_hash = self._calculate_file_hash(self.FILE_TO_CHECK_PATH)

        # 4. Compare the hashes
        self.assertEqual(expected_hash, actual_hash,
                         f"Hash mismatch for '{os.path.basename(self.FILE_TO_CHECK_PATH)}'. "
                         f"Expected: {expected_hash}, Got: {actual_hash} "
                         f"If the feature_flags.yaml file changed, generate a new no-op migration file, and correctly set the FileHash.")
