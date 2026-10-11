"""Freebox challenge authentication. No credentials are logged."""

import hashlib
import hmac


def challenge_password(app_token: str, challenge: str) -> str:
    """Freebox OS specifies HMAC-SHA1, not the admin password."""
    return hmac.new(app_token.encode(), challenge.encode(), hashlib.sha1).hexdigest()
