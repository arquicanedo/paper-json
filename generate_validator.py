"""Generate validator.py from schema.json.

Run:
    uv run generate_validator.py schema.json --out validator.py
    uv run generate_validator.py schema.json > validator.py   # also works

The generated validator.py is standalone and zero-dependency.
Do not hand-edit validator.py — edit schema.json and regenerate.

stdout is reconfigured to UTF-8 so the redirect form works on Windows
(default cp1252 mangles the em-dashes in the generated header).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


HEADER = '''\
# GENERATED — do not edit.
# Source: schema.json
# Regenerate: uv run generate_validator.py schema.json > validator.py
"""Validator for paper.json files following the LLM-Agent-Readable Paper convention.

Run:
    uv run validator.py path/to/paper.json
    uv run validator.py https://github.com/owner/repo
    uv run validator.py path/to/paper.json --against path/to/paper.typ

Exit codes:
    0 = valid
    1 = schema violation
    2 = cross-reference violation (C/D/T/F IDs in paper.json missing from source, or vice versa)
    3 = file not found / fetch failed
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

def _github_to_raw(url: str) -> str:
    """Rewrite a github.com repo URL to its raw paper.json URL."""
    url = url.rstrip("/")
    url = url.replace("https://github.com/", "https://raw.githubusercontent.com/")
    if not url.endswith("/paper.json"):
        url += "/main/paper.json"
    return url

def _fetch_remote(url: str) -> dict:
    raw_url = _github_to_raw(url) if "github.com" in url and not url.endswith(".json") else url
    with urllib.request.urlopen(raw_url) as resp:
        return json.loads(resp.read().decode("utf-8")), raw_url

'''

VALIDATE_VALUE = '''\
def _validate_value(value, field_schema: dict, path: str, errors: list[str]) -> None:
    if value is None:
        return
    t = field_schema.get("type")
    if t == "string":
        if not isinstance(value, str):
            errors.append(f"{path}: expected string, got {type(value).__name__}")
            return
        if "pattern" in field_schema and not re.fullmatch(field_schema["pattern"], value):
            errors.append(f"{path}: {value!r} does not match pattern {field_schema['pattern']!r}")
        if "minLength" in field_schema and len(value) < field_schema["minLength"]:
            errors.append(f"{path}: too short ({len(value)} chars, need >={field_schema['minLength']})")
        if "enum" in field_schema and value not in field_schema["enum"]:
            errors.append(f"{path}: {value!r} not in {field_schema['enum']}")
    elif t == "array":
        if not isinstance(value, list):
            errors.append(f"{path}: expected array, got {type(value).__name__}")
            return
        if "minItems" in field_schema and len(value) < field_schema["minItems"]:
            errors.append(f"{path}: need >={field_schema['minItems']} items, got {len(value)}")
        item_schema = field_schema.get("items", {})
        for i, item in enumerate(value):
            _validate_value(item, item_schema, f"{path}[{i}]", errors)
    elif t == "object":
        if not isinstance(value, dict):
            errors.append(f"{path}: expected object, got {type(value).__name__}")
            return
        for req in field_schema.get("required", []):
            if req not in value:
                errors.append(f"{path}: missing required field {req!r}")
        props = field_schema.get("properties", {})
        allow_extra = field_schema.get("additionalProperties", True)
        for k, v in value.items():
            if k in props:
                _validate_value(v, props[k], f"{path}.{k}", errors)
            elif not allow_extra:
                errors.append(f"{path}: unexpected field {k!r} (additionalProperties: false)")
    elif t == "boolean":
        if not isinstance(value, bool):
            errors.append(f"{path}: expected boolean, got {type(value).__name__}")

'''

CROSS_CHECK = '''\
# Each entry: (json_array_name, id_prefix, label_singular)
_ID_CLASSES = [
    ("claims",         "C", "claim"),
    ("definitions",    "D", "definition"),
    ("theorems",       "T", "theorem"),
    ("follow_up_work", "F", "follow_up_work"),
]


def _cross_check_source(paper: dict, source_text: str) -> list[str]:
    errors: list[str] = []
    for array_name, prefix, label in _ID_CLASSES:
        json_ids = {item["id"] for item in paper.get(array_name, []) if "id" in item}
        for jid in json_ids:
            if jid not in source_text:
                errors.append(f"{label} {jid} declared in paper.json but not found in source")
        source_ids = set(re.findall(rf"\\b{prefix}[0-9]+\\b", source_text))
        for orphan in source_ids - json_ids:
            errors.append(f"{label} id {orphan} appears in source but not declared in paper.json")
    return errors

'''

MAIN_TEMPLATE = '''\
def validate_paper(paper: dict) -> list[str]:
    errors: list[str] = []
    schema = {schema_literal}
    required = schema.get("required", [])
    for key in required:
        if key not in paper:
            errors.append(f"missing required field: {{key}}")
    props = schema.get("properties", {{}})
    for key, value in paper.items():
        if key in props:
            _validate_value(value, props[key], key, errors)
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paper_json")
    ap.add_argument("--against", type=Path, help="Typst source (.typ) to cross-check claim IDs against.")
    args = ap.parse_args()

    label = args.paper_json
    if args.paper_json.startswith("http://") or args.paper_json.startswith("https://"):
        try:
            paper, raw_url = _fetch_remote(args.paper_json)
            label = raw_url
        except Exception as exc:
            print(f"error: could not fetch {{args.paper_json}}: {{exc}}", file=sys.stderr)
            return 3
    else:
        p = Path(args.paper_json)
        if not p.exists():
            print(f"error: {{p}} not found", file=sys.stderr)
            return 3
        with p.open("r", encoding="utf-8") as f:
            paper = json.load(f)

    errors = validate_paper(paper)
    if errors:
        print(f"SCHEMA: {{len(errors)}} violation(s) in {{label}}")
        for e in errors:
            print(f"  - {{e}}")
        return 1

    print(f"SCHEMA: ok ({{label}})")
    print(f"  claims:      {{len(paper.get('claims', []))}}")
    print(f"  definitions: {{len(paper.get('definitions', []))}}")
    print(f"  detectors:   {{len(paper.get('detectors', []))}}")
    print(f"  non-claims:  {{len(paper.get('does_not_claim', []))}}")
    print(f"  follow-up:   {{len(paper.get('follow_up_work', []))}}")

    if args.against:
        if not args.against.exists():
            print(f"error: {{args.against}} not found", file=sys.stderr)
            return 3
        source_text = args.against.read_text(encoding="utf-8")
        xrefs = _cross_check_source(paper, source_text)
        if xrefs:
            print(f"CROSS-REF: {{len(xrefs)}} violation(s) against {{args.against}}")
            for e in xrefs:
                print(f"  - {{e}}")
            return 2
        print(f"CROSS-REF: ok ({{args.against}})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def generate(schema_path: Path) -> str:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    # Embed schema as a Python literal (not JSON) so booleans are True/False not true/false
    schema_literal = repr(schema)
    main_code = MAIN_TEMPLATE.format(schema_literal=schema_literal)
    return HEADER + VALIDATE_VALUE + CROSS_CHECK + main_code


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("schema", type=Path, help="Path to schema.json")
    ap.add_argument("--out", type=Path, help="Write output to this path (UTF-8). Default: stdout.")
    args = ap.parse_args()
    if not args.schema.exists():
        print(f"error: {args.schema} not found", file=sys.stderr)
        sys.exit(1)
    output = generate(args.schema)
    if args.out:
        args.out.write_text(output, encoding="utf-8")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
