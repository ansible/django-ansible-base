import datetime
import uuid
from collections import namedtuple
from contextlib import contextmanager
from unittest import mock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from ansible_base.lib.testing.util import copy_fixture


@pytest.fixture
def randname():
    def _randname(prefix):
        return f"{prefix}-{uuid.uuid4().hex[:6]}"

    return _randname


@pytest.fixture
def local_authenticator(db):
    from ansible_base.authentication.models import Authenticator

    authenticator = Authenticator.objects.create(
        name="Test Local Authenticator",
        enabled=True,
        create_objects=True,
        users_unique=False,
        remove_users=True,
        type="ansible_base.authentication.authenticator_plugins.local",
        configuration={},
    )
    yield authenticator
    authenticator.authenticator_user.all().delete()
    authenticator.delete()


@pytest.fixture
def unauthenticated_api_client(db):
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def admin_api_client(db, admin_user, unauthenticated_api_client, local_authenticator):
    client = unauthenticated_api_client
    client.login(username="admin", password="password")
    yield client
    try:
        client.logout()
    except AttributeError:
        # The test might have logged the user out already (e.g. to test the logout signal)
        pass


@pytest.fixture
def user(db, django_user_model, local_authenticator):
    user = django_user_model.objects.create_user(username="user", password="password")
    yield user
    user.delete()


@pytest.fixture
def random_user(db, django_user_model, randname, local_authenticator):
    user = django_user_model.objects.create_user(username=randname("user"), password="password")
    yield user
    user.delete()


@pytest.fixture
def user_api_client(db, user, unauthenticated_api_client, local_authenticator):
    client = unauthenticated_api_client
    client.login(username="user", password="password")
    yield client
    try:
        client.logout()
    except AttributeError:
        # The test might have logged the user out already (e.g. to test the logout signal)
        pass


@pytest.fixture
def no_log_messages():
    """
    This fixture returns a function (a context manager) which allows you to disable
    logging for a very specific part of a test.
    """

    @contextmanager
    def f():
        import logging

        logging.disable(logging.CRITICAL)
        yield
        logging.disable(logging.NOTSET)

    return f


@pytest.fixture
def shut_up_logging(no_log_messages):
    """
    This fixture allows you to temporarily disable logging for an entire test.
    """
    with no_log_messages():
        yield


@pytest.fixture
def expected_log(no_log_messages):
    """
    This fixture returns a function (a context manager) which allows you to assert
    that a logger is called appropriately for a line or block of code.

    Use it as a fixture, and then in your test:

    with expected_log("path.to.logger", "info", "some substring"):
        # code that should trigger the log message

    Or you can use functools.partial to make it even more concise if you're
    testing the same logger a bunch of times:

    expected_log = partial(expected_log, "path.to.logger")

    with expected_log("info", "some substring"):
        # code that should trigger the log message
    """

    @contextmanager
    def f(patch, severity, substr, assert_not_called=False):
        with mock.patch(patch) as logger:
            with no_log_messages():
                yield
            sev_logger = getattr(logger, severity)
            if assert_not_called:
                sev_logger.assert_not_called()
            else:
                sev_logger.assert_called_once()
                args, kwargs = sev_logger.call_args
                assert substr in args[0]

    return f


@pytest.fixture
def rsa_keypair_factory():
    """
    This fixture returns a factory function that creates a new RSA keypair every time it is called.

    This is useful for tests that need to create multiple RSA keypairs. @copy_fixture isn't suitable
    because it only ends up creating one keypair, so this avoids the issue.

    A default instance of this fixture is available as rsa_keypair.
    """

    def rsa_keypair():
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key()
        private_key_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")
        public_key_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        RSAKeyPair = namedtuple("RSAKeyPair", ["private", "public"])
        return RSAKeyPair(private=private_key_bytes, public=public_key_bytes)

    return rsa_keypair


@pytest.fixture
def rsa_keypair(rsa_keypair_factory):
    return rsa_keypair_factory()


@copy_fixture(copies=3)
@pytest.fixture
def rsa_keypair_with_cert(rsa_keypair_factory):
    rsa_keypair = rsa_keypair_factory()
    private_key = serialization.load_pem_private_key(rsa_keypair.private.encode("utf-8"), password=None)
    public_key = serialization.load_pem_public_key(rsa_keypair.public.encode("utf-8"))
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"California"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, u"San Francisco"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"My Company"),
            x509.NameAttribute(NameOID.COMMON_NAME, u"mycompany.com"),
        ]
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(u"mycompany.com")]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )
    certificate_bytes = certificate.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    RSAKeyPairWithCert = namedtuple("RSAKeyPairWithCert", ["private", "public", "certificate"])
    return RSAKeyPairWithCert(private=rsa_keypair.private, public=rsa_keypair.public, certificate=certificate_bytes)
