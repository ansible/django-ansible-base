# OAuth bearer-token authentication

The `oauth_bearer` authenticator validates JWT access tokens issued by an
external OAuth 2.0 or OpenID Connect provider. It is intended for API access,
not browser login. Clients send the access token using:

```text
Authorization: Bearer <access-token>
```

The authenticator is implemented by
`ansible_base.authentication.authenticator_plugins.oauth_bearer` and is
registered with the `api_auth` category. It is considered only for standard
`Bearer` credentials. Local OAuth2 access tokens remain supported: after API
authenticators decline a token, `BearerAuthentication` tries the local OAuth2
handler when `ansible_base.oauth2_provider` is installed.

## Configure an authenticator

Create an enabled authenticator of type
`ansible_base.authentication.authenticator_plugins.oauth_bearer`. Configure
the following settings:

| Setting | Required | Purpose |
| --- | --- | --- |
| `ISSUER_URL` | Yes | Exact issuer expected in the JWT `iss` claim. |
| `AUDIENCE` | Yes | Configured audience that must appear in the JWT `aud` claim, whether the claim is a string or list. |
| `ID_KEY` | Yes | JWT claim containing the stable external identity, such as `sub` for users or `azp` for service principals. |
| `JWKS_URI` | One key source required | HTTPS endpoint for verification keys when discovery is not used. |
| `OIDC_ENDPOINT` | One key source required | Issuer base URL used for OIDC discovery. |
| `JWKS_URL_TIMEOUT` | No | JWKS request timeout in seconds; defaults to 30. |
| `USERINFO_URL_TIMEOUT` | No | UserInfo request timeout in seconds; defaults to 30. |
| `JWT_CLOCK_SKEW_TOLERANCE_SECONDS` | No | Expiration, not-before, and issued-at tolerance in seconds; defaults to 0 and permits 0 through 300. |
| `ALLOWED_ALGORITHMS` | No | Accepted asymmetric signing algorithms; defaults to `RS256`. |
| `JWKS_CACHE_TIMEOUT` | No | JWKS cache lifetime in seconds; defaults to 3600 and has a minimum of 60. |
| `GROUPS_CLAIM` | No | Group-membership claim used by authenticator maps; defaults to `groups`. |
| `USERINFO_URL` | No | Supplemental profile and group-claim endpoint. |
| `EMAIL_KEY`, `FIRST_NAME_KEY`, `LAST_NAME_KEY`, `USERNAME_KEY` | No | Optional mappings from validated claims to local user fields. |
| `SCOPE_KEY`, `READ_SCOPE_NAME`, `WRITE_SCOPE_NAME` | No | Token-scope mapping; defaults are `scope`, `read`, and `write`. |
| `VERIFY_SSL` | No | Verifies TLS certificates for JWKS, OIDC discovery, and UserInfo requests; defaults to `true`. |

`OIDC_ENDPOINT` uses `/.well-known/openid-configuration` when the
authenticator is created or updated. Discovery supplies `JWKS_URI` and, when
available, `USERINFO_URL`; while `OIDC_ENDPOINT` is set, it is the source of
truth for both values.

Example configuration:

```json
{
  "ISSUER_URL": "https://idp.example.com/realms/automation",
  "OIDC_ENDPOINT": "https://idp.example.com/realms/automation",
  "AUDIENCE": "automation-api",
  "ID_KEY": "sub",
  "GROUPS_CLAIM": "groups",
  "ALLOWED_ALGORITHMS": ["RS256"]
}
```

Do not configure the deployment's own OIDC issuer as an external issuer.

## Token validation and authorization

An unverified `iss` and `aud` are used only to choose a configured
authenticator. The selected authenticator then verifies the signature with its
JWKS, accepted asymmetric algorithms, issuer, audience, and expiration. It
requires `exp` and applies `JWT_CLOCK_SKEW_TOLERANCE_SECONDS` to `exp`, `nbf`,
and `iat` validation.

`SCOPE_KEY` defaults to `scope`. A token receives API `read` and `write`
permissions only when its configured `READ_SCOPE_NAME` or `WRITE_SCOPE_NAME`
is present. `write` implies `read`; a valid token without either scope is
authenticated but cannot access endpoints guarded by the shared token-scope
permission. Existing RBAC checks still apply.

## Identity, groups, and profile data

The value of `ID_KEY` identifies the provider association. A validated token
can create or update the associated local user and `AuthenticatorUser` record,
then applies authenticator maps using groups from `GROUPS_CLAIM`. Configure
`USERNAME_KEY` to choose a local username other than the external ID.

`EMAIL_KEY`, `FIRST_NAME_KEY`, and `LAST_NAME_KEY` optionally map validated
claims to local profile fields. If `USERINFO_URL` is configured, accepted
UserInfo claims supplement the access-token claims for groups and profile data.
A UserInfo response must identify the same subject as the validated access
token. UserInfo is supplementary: an unavailable or unusable response does not
invalidate an otherwise valid access token.

The system user, when `SYSTEM_USERNAME` is configured, and inactive users
cannot authenticate through this authenticator. Treat `ID_KEY` as immutable for
an external identity; changing it can create a different local association.

## JWKS and availability

JWKS are cached for `JWKS_CACHE_TIMEOUT` seconds (default 3600; minimum 60).
On a signature failure, the authenticator can refresh the provider key set
once to handle key rotation. `JWKS_URL_TIMEOUT` controls JWKS requests and
`USERINFO_URL_TIMEOUT` controls UserInfo requests. `VERIFY_SSL` should remain
enabled outside a controlled development environment.

An expired or invalid token returns an RFC 6750 Bearer challenge. An
unavailable JWKS provider is reported as an authentication-service failure;
applications should monitor these failures rather than accepting a token
without verification.
