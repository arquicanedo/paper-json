"""Resolve <node_id>#<id> URIs to the matching item in a paper.json.

This is the reference resolver for the paper.json convention's fragment syntax.
The convention defines `<network.node_id>#<id>` as the canonical global reference
for any claim, definition, theorem, or follow-up item, where `id` is one of
C[0-9]+, D[0-9]+, T[0-9]+, or F[0-9]+, and `network.node_id` is typically the
URL of the host repository.

HTTP fragments are client-side. This script handles two steps that HTTP alone
does not: discovering the paper.json from a repo URL (raw-URL rewrite for
GitHub, /paper.json well-known path otherwise), and parsing the #<id> fragment.

Run:
    uv run resolve.py "https://github.com/arquicanedo/paper-json#C1"
    uv run resolve.py "https://github.com/arquicanedo/paper-json#C1" --raw
    uv run resolve.py "paper.json#C1" --local

Resolution strategy for the base URL (the part before #):
    1. If the URL is a GitHub repo (github.com/<user>/<repo>) or a GitHub tree
       URL (github.com/<user>/<repo>/tree/<branch>/<path>), rewrite to the raw
       endpoint at raw.githubusercontent.com and try `main` then `master`.
    2. Otherwise, try `<base>/paper.json` (the .well-known convention).
    3. If --local is set, treat the part before # as a local file path.

Exit codes:
    0 = resolved
    1 = fragment id not found in paper.json
    2 = fetch failed
    3 = invalid URI / file not found
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


ID_TO_ARRAY = {
    "C": ("claims", "claim"),
    "D": ("definitions", "definition"),
    "T": ("theorems", "theorem"),
    "F": ("follow_up_work", "follow_up_work_item"),
}


def split_uri(uri: str) -> tuple[str, str]:
    if "#" not in uri:
        print(f"error: URI {uri!r} has no fragment (expected <base>#<id>)", file=sys.stderr)
        sys.exit(3)
    base, _, fragment = uri.partition("#")
    if not fragment:
        print(f"error: empty fragment in {uri!r}", file=sys.stderr)
        sys.exit(3)
    return base, fragment


def github_raw_candidates(base: str) -> list[str]:
    """Map a github.com URL to candidate raw paper.json URLs.

    Handles both the repo-root form (github.com/<user>/<repo>) and the tree
    form (github.com/<user>/<repo>/tree/<branch>/<subdir>).
    """
    parsed = urlparse(base)
    if parsed.netloc != "github.com":
        return []
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return []
    user, repo = parts[0], parts[1]

    if len(parts) >= 4 and parts[2] == "tree":
        branch = parts[3]
        subpath = "/".join(parts[4:])
        prefix = f"https://raw.githubusercontent.com/{user}/{repo}/{branch}"
        return [f"{prefix}/{subpath}/paper.json".replace("//paper.json", "/paper.json")]

    return [
        f"https://raw.githubusercontent.com/{user}/{repo}/main/paper.json",
        f"https://raw.githubusercontent.com/{user}/{repo}/master/paper.json",
    ]


def fallback_candidate(base: str) -> str:
    return base.rstrip("/") + "/paper.json"


MAX_BYTES = 10 * 1024 * 1024  # 10 MB cap on a single paper.json fetch
ALLOWED_SCHEMES = {"http", "https"}
MAX_REDIRECTS = 5


class _CappedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def http_error_302(self, req, fp, code, msg, headers):
        new_url = headers.get("Location", "")
        scheme = urlparse(new_url).scheme.lower() if new_url else ""
        if scheme and scheme not in ALLOWED_SCHEMES:
            raise urllib.error.URLError(f"refusing redirect to non-http(s) scheme: {scheme!r}")
        return super().http_error_302(req, fp, code, msg, headers)
    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


_OPENER = urllib.request.build_opener(_CappedRedirectHandler())
_OPENER.addheaders = [("User-Agent", "paper-json-resolve/0.1")]


def fetch_remote(url: str, timeout: float = 10.0) -> dict:
    scheme = urlparse(url).scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise urllib.error.URLError(f"refusing non-http(s) scheme: {scheme!r}")
    with _OPENER.open(url, timeout=timeout) as resp:
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype and ctype not in {"application/json", "text/plain", "text/json", "application/octet-stream"}:
            raise urllib.error.URLError(f"unexpected Content-Type {ctype!r} (want application/json)")
        body = resp.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise urllib.error.URLError(f"response exceeds {MAX_BYTES} bytes; refusing to load")
        return json.loads(body.decode("utf-8"))


def resolve_remote(base: str) -> tuple[dict, str]:
    """Return (paper_dict, url_actually_fetched). Tries GitHub raw URLs then fallback."""
    candidates = github_raw_candidates(base) or []
    candidates.append(fallback_candidate(base))

    last_err: Exception | None = None
    for url in candidates:
        try:
            return fetch_remote(url), url
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
            last_err = e
            continue
    print(f"error: could not fetch paper.json from any of {candidates}", file=sys.stderr)
    if last_err:
        print(f"  last error: {last_err}", file=sys.stderr)
    sys.exit(2)


def load_local(path_str: str) -> dict:
    path = Path(path_str)
    if not path.exists():
        print(f"error: local paper.json not found at {path}", file=sys.stderr)
        sys.exit(3)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"error: {path} is not valid JSON: {e}", file=sys.stderr)
        sys.exit(3)


def find_item(paper: dict, fragment: str) -> tuple[dict, str]:
    """Return (item, item_type) or exit 1 if not found."""
    prefix = fragment[:1]
    array_info = ID_TO_ARRAY.get(prefix)
    if not array_info:
        print(f"error: fragment {fragment!r} has no recognized prefix (expected C, D, T, or F)", file=sys.stderr)
        sys.exit(1)
    array_name, item_type = array_info
    items = paper.get(array_name, [])
    for item in items:
        if item.get("id") == fragment:
            return item, item_type
    print(f"error: id {fragment!r} not found in {array_name}[]", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("uri", help="<node_id>#<id> for remote, or <path>#<id> with --local")
    ap.add_argument("--local", action="store_true", help="Resolve against a local paper.json instead of fetching")
    ap.add_argument("--raw", action="store_true", help="Print only the matching item (no metadata wrapper)")
    args = ap.parse_args()

    base, fragment = split_uri(args.uri)

    if args.local:
        paper = load_local(base)
        source_url = base
    else:
        paper, source_url = resolve_remote(base)

    item, item_type = find_item(paper, fragment)

    if args.raw:
        print(json.dumps(item, indent=2, ensure_ascii=False))
    else:
        wrapper = {
            "resolved_from": source_url,
            "fragment": fragment,
            "item_type": item_type,
            "paper_id": paper.get("id"),
            "paper_title": paper.get("title"),
            "paper_version": paper.get("version"),
            "item": item,
        }
        print(json.dumps(wrapper, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
