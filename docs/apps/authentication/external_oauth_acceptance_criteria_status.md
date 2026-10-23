# External OAuth Acceptance Criteria Status

Current implementation assessment for the related external OAuth authentication stories.

| Jira | AC | Status | Details | Action |
| --- | --- | --- | --- |
| AAP-66708 | JWT Bearer token validates against matching external OAuth provider | Done | External plugin routes by unverified issuer/audience, then validates signature through JWKS. | None |
| AAP-66708 | Validate issuer, audience, expiration, and subject | Done | Issuer/audience/required `exp`, signature, and allowed algorithms validate. Identity is configurable through ordered `CLAIM_LIST`; `sub` is supported but not mandatory. | None |
| AAP-66708 | Non-external OAuth tokens fall through | Done | Opaque/foreign tokens decline in the plugin. A presented Bearer credential ends in 401 after all Bearer handlers—including local OAuth—decline it. | None |
| AAP-66708 | No existing-auth regression | Done | Focused unit coverage is green. Broader end-to-end product regression validation is deferred to M7. | None |
| AAP-66709 | JWKS cache has configurable TTL | Done | Shared Django cache uses each provider's `JWKS_CACHE_TIMEOUT`. | None |
| AAP-66709 | Refresh after key rotation | Done | Invalid signature triggers one fresh-key retry. | None |
| AAP-66709 | Refresh cooldown prevents DoS | Done | Shared-cache 60-second forced-refresh cooldown is implemented and tested. | None |
| AAP-66709 | Cached keys permit graceful provider outage | Done | Normal cached-key validation continues during a provider outage. A forced refresh that fails does not retry with the prior cached key. | None |
| AAP-66710 | Multi-provider issuer/audience routing with O(1) lookup | Done | Plugins route by issuer/audience and cache all API authenticators; dispatch deliberately iterates the small cached list in configured order. | None |
| AAP-66710 | Authenticator order resolves overlapping providers | Done | API authenticators load and run in configured `order`; first successful result wins. | None |
| AAP-66710 | Provider cache refreshes on configuration change | Done | LRU cache key derives from latest API-authenticator modification time, including disabled rows for state-change invalidation. | None |
| AAP-66711 | Every attempt is audit logged without raw token values | Done | Successful API plugin auth uses `log_auth_event`; unexpected plugin exceptions use `log_auth_exception`. Ordinary expected validation failures use standard logger calls, matching the convention used by other authenticators. | None |
| AAP-66711 | Generic client errors, detailed server context | Done | Client-safe failures distinguish invalid, expired, and provider-unavailable credentials without exposing provider details; diagnostic context remains server-side. | None |
| AAP-66711 | RFC 6750 `WWW-Authenticate` response | Done | Bearer failures return RFC 6750 challenges with safe `invalid_token` details. | None |
| AAP-95658 | Evaluate matching external authenticators in configured order | Done | Bearer dispatcher invokes cached API authenticators in `order`; matching external OAuth plugins decline nonmatching tokens. | None |
| AAP-95658 | Resolve identity claims in configured claim-list order | Done | `resolve_uid_from_claims()` selects the first present, usable scalar claim from `CLAIM_LIST`. | None |
| AAP-95658 | Define/test authoritative present-claim and failed-match behavior | Done | Unit tests establish first usable claim semantics and verify a later matching authenticator can succeed when an earlier one declines. | None |
| AAP-95659 | Map service-principal claims to standard users via `AuthenticatorUser` | Done | `azp` and `client_id` can be configured in `CLAIM_LIST`; the first usable claim becomes the `uid` passed to `get_or_create_authenticator_user()`. | None |
| AAP-95659 | Preserve normal RBAC administration | Done | Resulting standard users go through normal claims/map processing and RBAC structures; focused tests verify the service-principal mapping path. | None |
