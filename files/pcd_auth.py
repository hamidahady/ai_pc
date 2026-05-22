"""
pcd_auth.py — pick the best available Anthropic credential and build a client.

Priority order:
  1. Claude Code's OAuth tokens from %USERPROFILE%\\.claude\\.credentials.json
     (uses the user's Claude.ai subscription — no API credits needed).
  2. Environment variable ANTHROPIC_API_KEY (the metered API path).

When using Claude Code's OAuth, we pass the access token as a Bearer header
via the SDK's `auth_token` parameter and add the OAuth beta header so
Anthropic accepts the subscription-tied identity.

The token is read fresh on every call so any refresh Claude Code performs
in the background is picked up automatically. If the token is expired and
no API key is available, the dashboard surfaces a clear, actionable error.
"""

import json
import os
import time
from pathlib import Path

from pcd_log import logger

CREDS_PATH = Path.home() / ".claude" / ".credentials.json"

# Beta header that tells Anthropic "this Bearer token is a Claude Code
# OAuth credential — bill against the user's Claude.ai subscription, not
# against API credits."
_OAUTH_BETA_HEADER = "oauth-2025-04-20"


def _read_oauth() -> dict | None:
    """Return the parsed claudeAiOauth dict, or None if unreadable."""
    try:
        if not CREDS_PATH.exists():
            return None
        with open(CREDS_PATH, encoding="utf-8") as f:
            return json.load(f).get("claudeAiOauth") or None
    except Exception as e:
        logger.warning("auth: cannot read %s: %s", CREDS_PATH, e)
        return None


def _oauth_is_valid(oauth: dict, slack_seconds: int = 60) -> bool:
    """True if the access token is present and not within `slack_seconds`
    of expiring. A small slack avoids racing the expiry boundary."""
    token = oauth.get("accessToken")
    expires_at_ms = oauth.get("expiresAt", 0)
    if not token or not expires_at_ms:
        return False
    return expires_at_ms / 1000 > time.time() + slack_seconds


def auth_status() -> dict:
    """Report which auth paths are usable right now. Used by
    /api/chat/status so the chat panel can show the correct message."""
    oauth = _read_oauth()
    oauth_ok = bool(oauth) and _oauth_is_valid(oauth)
    api_key_ok = bool(os.environ.get("ANTHROPIC_API_KEY"))
    out = {
        "oauth_present":  bool(oauth),
        "oauth_valid":    oauth_ok,
        "api_key_set":    api_key_ok,
        "subscription_type": (oauth or {}).get("subscriptionType"),
        "rate_limit_tier":   (oauth or {}).get("rateLimitTier"),
    }
    # Choose source for display
    if oauth_ok:
        out["active_source"] = "claude_code_oauth"
    elif api_key_ok:
        out["active_source"] = "api_key"
    else:
        out["active_source"] = None
    # When the OAuth token has expired we say so explicitly so the user knows
    # the fix is to run `claude` once (Claude Code will refresh it).
    if oauth and not oauth_ok:
        expires_at_ms = oauth.get("expiresAt", 0)
        out["oauth_expired_at_unix"] = expires_at_ms / 1000 if expires_at_ms else None
    return out


def build_anthropic_client():
    """Return (client, source). source is 'api_key' | 'claude_code_oauth' | None.

    Priority order:
      1. ANTHROPIC_API_KEY if set in the environment. The user explicitly
         setting this is a signal they want metered-API billing with its
         own independent quota (no overlap with Claude Code's subscription).
      2. Claude Code's OAuth token from ~/.claude/.credentials.json.
         Caveat: Anthropic heavily rate-limits Claude.ai subscription tokens
         when they're used outside Claude Code itself, so this works for
         occasional questions but will 429 quickly under any real use while
         Claude Code is also active.

    Caller checks source: if None, no usable credential was found.
    """
    import anthropic  # imported lazily so this module is importable without it

    # API key first — separate quota, no contention with Claude Code.
    if os.environ.get("ANTHROPIC_API_KEY"):
        return anthropic.Anthropic(), "api_key"

    oauth = _read_oauth()
    if oauth and _oauth_is_valid(oauth):
        try:
            client = anthropic.Anthropic(
                auth_token=oauth["accessToken"],
                default_headers={"anthropic-beta": _OAUTH_BETA_HEADER},
            )
            return client, "claude_code_oauth"
        except Exception as e:
            logger.warning("auth: OAuth client init failed (%s)", e)

    return None, None
