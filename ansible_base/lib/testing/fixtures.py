import datetime
import os
import uuid
from collections import namedtuple
from contextlib import contextmanager
from unittest import mock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from rest_framework.test import APIClient

from ansible_base.lib.testing.util import copy_fixture, delete_authenticator


@pytest.fixture
def randname():
    def _randname(prefix):
        return f"{prefix}-{uuid.uuid4().hex[:6]}"

    return _randname


@pytest.fixture
def env():
    """
    Set an environment variable within a context manager.
    """

    @contextmanager
    def _env(key, value):
        old_value = os.environ.get(key)
        os.environ[key] = value
        yield
        if old_value is None:
            del os.environ[key]
        else:
            os.environ[key] = old_value

    return _env


@pytest.fixture
def local_authenticator(db):
    from ansible_base.authentication.models import Authenticator

    authenticator = Authenticator.objects.create(
        name="Test Local Authenticator",
        enabled=True,
        create_objects=True,
        remove_users=True,
        type="ansible_base.authentication.authenticator_plugins.local",
        configuration={},
    )
    return authenticator


@pytest.fixture
def unauthenticated_api_client(db):
    return APIClient()


@pytest.fixture
def admin_api_client(db, admin_user, local_authenticator):
    # We don't use the is_staff flag anywhere. Instead we use is_superuser. This can
    # cause some permission checks to unexpectedly break in production where this flag
    # never gets set to true.
    admin_user.is_staff = False
    admin_user.save()
    client = APIClient()
    client.login(username="admin", password="password")
    yield client
    try:
        client.logout()
    except AttributeError:
        # The test might have logged the user out already (e.g. to test the logout signal)
        pass


@pytest.fixture
def user(db, django_user_model, local_authenticator):
    return django_user_model.objects.create_user(username="user", password="password")


@copy_fixture(copies=3)
@pytest.fixture
def random_user(db, django_user_model, randname, local_authenticator):
    return django_user_model.objects.create_user(username=randname("user"), password="password")


@pytest.fixture
def user_api_client(db, user, local_authenticator):
    client = APIClient()
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
        with mock.patch(f'{patch}.{severity}') as logger:
            with no_log_messages():
                yield

            call_count = sum(1 for call in logger.call_args_list if substr in call.args[0])

            if assert_not_called:
                assert call_count == 0, f"Expected 0 calls but got {call_count}"
            else:
                assert call_count == 1, f"Expected 1 call but got {call_count}"

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


@pytest.fixture
def ldap_configuration():
    return {
        "SERVER_URI": ["ldap://ldap06.example.com:389"],
        "BIND_DN": "cn=ldapadmin,dc=example,dc=org",
        "BIND_PASSWORD": "securepassword",
        "START_TLS": False,
        "CONNECTION_OPTIONS": {"OPT_REFERRALS": 0, "OPT_NETWORK_TIMEOUT": 30},
        "USER_SEARCH": ["ou=users,dc=example,dc=org", "SCOPE_SUBTREE", "(cn=%(user)s)"],
        "USER_DN_TEMPLATE": "cn=%(user)s,ou=users,dc=example,dc=org",
        "USER_ATTR_MAP": {"email": "mail", "last_name": "sn", "first_name": "givenName"},
        "GROUP_SEARCH": ["ou=groups,dc=example,dc=org", "SCOPE_SUBTREE", "(objectClass=groupOfNames)"],
        "GROUP_TYPE": "MemberDNGroupType",
        "GROUP_TYPE_PARAMS": {"name_attr": "cn", "member_attr": "member"},
    }


@pytest.fixture
def ldap_authenticator(ldap_configuration):
    from ansible_base.authentication.models import Authenticator

    authenticator = Authenticator.objects.create(
        name="Test LDAP Authenticator",
        enabled=True,
        create_objects=True,
        remove_users=True,
        type="ansible_base.authentication.authenticator_plugins.ldap",
        configuration=ldap_configuration,
    )
    yield authenticator
    delete_authenticator(authenticator)
