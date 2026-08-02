"""URL normalisation for the add-an-essay uniqueness check.

Lowercase the host, drop www., drop the trailing slash, drop tracking parameters.

This catches the easy cases and only the easy cases. A Substack post that also lives on
a personal domain will slip through as two essays. That gap is accepted for the MVP —
the fix is EssayAlias plus content-hash dedupe, and both need a fetch we are not doing.
Watch for duplicates in the admin instead.
"""

from urllib.parse import parse_qsl, urlsplit, urlunsplit, urlencode

TRACKING_PREFIXES = ("utm_",)
TRACKING_KEYS = {"ref", "ref_src", "referrer", "source", "fbclid", "gclid", "mc_cid", "mc_eid"}


def normalise_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw

    parts = urlsplit(raw)
    scheme = "https" if parts.scheme in ("http", "https") else parts.scheme.lower()

    host = parts.hostname or ""
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    netloc = host
    if parts.port and parts.port not in (80, 443):
        netloc = f"{host}:{parts.port}"

    path = parts.path.rstrip("/") or "/"

    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_KEYS
        and not k.lower().startswith(TRACKING_PREFIXES)
    ]
    query = urlencode(kept)

    # The fragment goes: #section-3 is the same essay as the essay.
    return urlunsplit((scheme, netloc, path, query, ""))


def host_of(raw: str) -> str:
    try:
        return urlsplit(normalise_url(raw)).hostname or ""
    except ValueError:
        return ""
