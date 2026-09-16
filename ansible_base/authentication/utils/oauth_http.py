# Truncate IdP error bodies so a token-endpoint failure is visible in Gateway
# logs without dumping an unbounded response.
OAUTH_HTTP_ERROR_BODY_LIMIT = 2000


def oauth_http_error_body(response, limit=OAUTH_HTTP_ERROR_BODY_LIMIT) -> str:
    """Return a truncated HTTP response body, or empty string if unavailable."""
    if response is None:
        return ""
    try:
        return (response.text or "")[:limit]
    except Exception:
        return ""


def format_oauth_http_error(authenticator_name, err, body_limit=OAUTH_HTTP_ERROR_BODY_LIMIT) -> str:
    """Build the auth-audit line for a provider HTTPError (e.g. Azure AADSTS)."""
    response = getattr(err, "response", None)
    status = getattr(response, "status_code", None)
    body = oauth_http_error_body(response, limit=body_limit)
    return f"OAuth HTTP error for authenticator '{authenticator_name}' status={status} body={body}"
