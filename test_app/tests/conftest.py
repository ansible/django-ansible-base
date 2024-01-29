import datetime
import uuid
from collections import namedtuple
from contextlib import contextmanager
from unittest import mock

import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from django.test.client import RequestFactory


def copy_fixture(copies=1):
    """
    Decorator to create 'copies' copies of a fixture.

    The copies will be named func_1, func_2, ..., func_n in the same module as
    the original fixture.
    """

    def wrapper(func):
        if '_pytestfixturefunction' not in dir(func):
            raise TypeError(f"Can't apply copy_fixture to {func.__name__} because it is not a fixture. HINT: @copy_fixture must be *above* @pytest.fixture")

        module_name = func.__module__
        module = __import__(module_name, fromlist=[''])

        for i in range(copies):
            new_name = f"{func.__name__}_{i + 1}"
            setattr(module, new_name, func)
        return func

    return wrapper


@pytest.fixture
def randname():
    def _randname(prefix):
        return f"{prefix}-{uuid.uuid4().hex[:6]}"

    return _randname


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
        users_unique=False,
        remove_users=True,
        type="ansible_base.authentication.authenticator_plugins.ldap",
        configuration=ldap_configuration,
    )
    yield authenticator
    authenticator.delete()


@pytest.fixture
def saml_configuration(rsa_keypair_with_cert, rsa_keypair_with_cert_1):
    return {
        "CALLBACK_URL": "https://localhost/api/social/complete/ansible_base-authenticator_plugins-saml__test-saml-authenticator/",
        "SP_ENTITY_ID": "saml_entity",
        "SP_PUBLIC_CERT": rsa_keypair_with_cert.certificate,
        "SP_PRIVATE_KEY": rsa_keypair_with_cert.private,
        "ORG_INFO": {"en-US": {"url": "http://localhost", "name": "test app", "displayname": "Test App"}},
        "TECHNICAL_CONTACT": {'givenName': "Technical Doe", 'emailAddress': "tdoe@example.com"},
        "SUPPORT_CONTACT": {'givenName': "Support Doe", 'emailAddress': "sdoe@example.com"},
        "SP_EXTRA": {"requestedAuthnContext": False},
        "SECURITY_CONFIG": {},
        "EXTRA_DATA": [],
        "IDP_URL": "https://idp.example.com/idp/profile/SAML2/Redirect/SSO",
        "IDP_X509_CERT": rsa_keypair_with_cert_1.certificate,
        "IDP_ENTITY_ID": "https://idp.example.com/idp/shibboleth",
        "IDP_GROUPS": "groups",
        "IDP_ATTR_EMAIL": "email",
        "IDP_ATTR_USERNAME": "username",
        "IDP_ATTR_LAST_NAME": "last_name",
        "IDP_ATTR_FIRST_NAME": "first_name",
        "IDP_ATTR_USER_PERMANENT_ID": "user_permanent_id",
    }


@pytest.fixture
def saml_authenticator(saml_configuration):
    from ansible_base.authentication.models import Authenticator

    authenticator = Authenticator.objects.create(
        name="Test SAML Authenticator",
        enabled=True,
        create_objects=True,
        users_unique=False,
        remove_users=True,
        type="ansible_base.authentication.authenticator_plugins.saml",
        configuration=saml_configuration,
    )
    yield authenticator
    authenticator.delete()


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
def custom_authenticator(db):
    from ansible_base.authentication.models import Authenticator

    authenticator = Authenticator.objects.create(
        name="Test Custom Authenticator",
        enabled=True,
        create_objects=True,
        users_unique=False,
        remove_users=True,
        type="test_app.tests.fixtures.authenticator_plugins.custom",
        configuration={},
    )
    yield authenticator
    authenticator.authenticator_user.all().delete()
    authenticator.delete()


@pytest.fixture
def keycloak_authenticator(db):
    from ansible_base.authentication.models import Authenticator

    authenticator = Authenticator.objects.create(
        name="Test Keycloak Authenticator",
        enabled=True,
        create_objects=True,
        users_unique=False,
        remove_users=True,
        type="ansible_base.authentication.authenticator_plugins.keycloak",
        configuration={
            "ACCESS_TOKEN_URL": "asdf",
            "AUTHORIZATION_URL": "asdf",
            "KEY": "asdf",
            "PUBLIC_KEY": "asdf",
            "SECRET": "asdf",
        },
    )
    yield authenticator
    authenticator.delete()


@copy_fixture(copies=3)
@pytest.fixture
def local_authenticator_map(db, local_authenticator, user, randname):
    from ansible_base.authentication.models import AuthenticatorMap

    authenticator_map = AuthenticatorMap.objects.create(
        name=randname("Test Local Authenticator Map"),
        authenticator=local_authenticator,
        map_type="is_superuser",
        triggers={"always": {}},
        organization="testorg",
        team="testteam",
    )
    yield authenticator_map
    authenticator_map.delete()


# Generate public and private keys for testing
private_key = rsa.generate_private_key(public_exponent=65537, key_size=4096, backend=default_backend())


@pytest.fixture
def test_encryption_private_key():
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


@pytest.fixture
def test_encryption_public_key():
    return (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )


@pytest.fixture
def jwt_token(test_encryption_private_key):
    class Token:
        def __init__(self):
            expiration_date = datetime.datetime.now() + datetime.timedelta(minutes=10)
            self.unencrypted_token = {
                "iss": "ansible-issuer",
                "exp": int(expiration_date.timestamp()),
                "aud": "ansible-services",
                "sub": "john.westcott.iv",
                "first_name": "john",
                "last_name": "westcott",
                "email": "noone@redhat.com",
                "is_superuser": False,
                "is_system_auditor": False,
                "claims": {"organizations": {}, "teams": {}},
            }

        def encrypt_token(self):
            return jwt.encode(self.unencrypted_token, test_encryption_private_key, algorithm="RS256")

    test_token = Token()
    return test_token


@pytest.fixture
def mocked_http(test_encryption_public_key, jwt_token):
    class MockedHttp:
        def mocked_get_decryption_key_get_request(self, *args, **kwargs):
            class MockResponse:
                def __init__(self, text, status_code):
                    self.status_code = 200
                    self.text = text
                    self.status_code = status_code

            if args[0] == 'http://someotherurl.com/200_junk/api/gateway/v1/jwt_key/':
                return MockResponse("Junk", 200)
            elif args[0] == 'http://someotherurl.com/200_good/api/gateway/v1/jwt_key/':
                return MockResponse(test_encryption_public_key, 200)
            elif args[0] == 'http://someotherurl.com/302/api/gateway/v1/jwt_key/':
                return MockResponse(None, 302)
            elif args[0] == 'http://someotherurl.com/504/api/gateway/v1/jwt_key/':
                return MockResponse(None, 504)

            return MockResponse(None, 404)

        def mocked_parse_jwt_token_get_request(self, *args, **kwargs):
            rf = RequestFactory()
            get_request = rf.get('/hello/')
            if args[0] == 'with_headers':
                get_request.headers = {'X-DAB-JW-TOKEN': jwt_token.encrypt_token()}
            return get_request

        def mocked_gateway_view_get_request(self, *args, **kwargs):
            # First argument is whether or not the user should be authenticated
            rf = RequestFactory()
            get_request = rf.get('/hello/')

            mocked_user = mock.Mock(is_authenticated=args[0])
            get_request.user = mocked_user
            get_request.session = {}
            return get_request

    return MockedHttp()


@pytest.fixture
def system_user_without_self_reference(db, settings, no_log_messages):
    settings.SYSTEM_USERNAME = '_system'
    from test_app.models import User

    with no_log_messages():
        user_obj = User.objects.create_user(settings.SYSTEM_USERNAME)
    assert user_obj.created_by is None
    assert user_obj.modified_by is None
    yield user_obj
    user_obj.delete()


@pytest.fixture
def system_user(system_user_without_self_reference):
    sys_user = system_user_without_self_reference
    sys_user.created_by = sys_user
    sys_user.save()
    sys_user.refresh_from_db()
    assert sys_user.created_by == sys_user
    assert sys_user.modified_by == sys_user
    yield sys_user
    # system_user_without_self_reference cleans up after itself


@pytest.fixture
def organization(db, randname):
    from test_app.models import Organization

    organization = Organization.objects.create(name=randname("Test Organization"))
    yield organization
    organization.delete()
