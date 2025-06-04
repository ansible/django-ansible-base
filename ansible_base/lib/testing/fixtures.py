import copy
import os
import uuid
from collections import namedtuple
from contextlib import contextmanager
from datetime import datetime, timedelta
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
        try:
            yield
        finally:
            if old_value is None:
                del os.environ[key]
            else:
                os.environ[key] = old_value

    return _env


@pytest.fixture
def settings_override_mutable(settings):
    """
    pytest-django's settings  doesn't handle mutable settings types well
    (https://github.com/pytest-dev/pytest-django/issues/601). This fixture is an
    attempt to solve that problem.

    Use as follows:

    def test_foo(settings, settings_override_mutable):
        with settings_override_mutable("SOME_SETTING_VAR"):
            settings.SOME_SETTING_VAR['and']['nested']['a']['bit'] = "new_value"
            # or even
            delattr(settings, 'SOME_SETTING_VAR')  # for some reason normal "del" doesn't work here
        # But out of the context manager the whole var is restored
        assert settings.SOME_SETTING_VAR['and']['nested']['a']['bit'] == "old_value"
    """

    @contextmanager
    def f(setting_key):
        original = copy.deepcopy(getattr(settings, setting_key))
        try:
            yield
        finally:
            setattr(settings, setting_key, original)

    return f


@pytest.fixture
def local_authenticator(db):
    from ansible_base.authentication.models import Authenticator

    authenticator = Authenticator.objects.create(
        name="Test Local Authenticator",
        enabled=True,
        create_objects=True,
        remove_users=False,
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
        try:
            yield
        finally:
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
def rsa_keypair_with_signed_cert(rsa_keypair_factory):
    root_keypair = rsa_keypair_factory()
    root_private_key = serialization.load_pem_private_key(root_keypair.private.encode("utf-8"), password=None)
    root_public_key = serialization.load_pem_public_key(root_keypair.public.encode("utf-8"))
    rsa_keypair = rsa_keypair_factory()
    public_key = serialization.load_pem_public_key(rsa_keypair.public.encode("utf-8"))
    issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"California"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, u"San Francisco"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"My Company"),
            x509.NameAttribute(NameOID.COMMON_NAME, u"mycompany.com"),
        ]
    )
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"California"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, u"San Francisco"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"My Company"),
            x509.NameAttribute(NameOID.COMMON_NAME, u"qa.mycompany.com"),
        ]
    )
    root_certificate = (
        x509.CertificateBuilder()
        .subject_name(issuer)
        .issuer_name(issuer)
        .public_key(root_public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow())
        .not_valid_after(datetime.utcnow() + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(u"mycompany.com")]),
            critical=False,
        )
        .sign(root_private_key, hashes.SHA256())
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow())
        .not_valid_after(datetime.utcnow() + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(u"qa.mycompany.com")]),
            critical=False,
        )
        .sign(root_private_key, hashes.SHA256())
    )

    root_certificate_bytes = root_certificate.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    certificate_bytes = certificate.public_bytes(serialization.Encoding.PEM).decode("utf-8")

    RSAKeyPairWithCert = namedtuple("RSAKeyPairWithCert", ["private", "public", "certificate"])
    CertificateChain = namedtuple("CertificateChain", ["root", "subordinate"])

    root_keypair_with_cert = RSAKeyPairWithCert(private=root_keypair.private, public=root_keypair.public, certificate=root_certificate_bytes)
    subordinate_keypair_with_cert = RSAKeyPairWithCert(private=rsa_keypair.private, public=rsa_keypair.public, certificate=certificate_bytes)
    return CertificateChain(root=root_keypair_with_cert, subordinate=subordinate_keypair_with_cert)


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
        .not_valid_before(datetime.utcnow())
        .not_valid_after(datetime.utcnow() + timedelta(days=365))
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


@pytest.fixture
def aap_flags():
    from ansible_base.feature_flags.utils import create_initial_data

    create_initial_data()


@pytest.fixture
def create_mock_method():
    # Creates a function that when called, generates a function that can be used to patch
    # a method. Useful for when you want to mock an object method that modifies an object's state.
    # Accepts arguments:
    #   field_dicts: iterable of dictionaries containing key-value pairs to modify for parent object
    def mock_method_generator(field_dicts: list[dict]):
        def create_generator():
            for field_dict in field_dicts:
                yield field_dict

        generator = create_generator()

        def mock_method(self, ignore_cache=False):
            # Get dictionary of fields to modify
            fields = next(generator)
            # Modify JWTCert object with each field defined in the fields dictionary
            for field, value in fields.items():
                setattr(self, field, value)

        return mock_method

    return mock_method_generator
