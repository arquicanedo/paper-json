# GENERATED — do not edit.
# Source: schema.json
# Regenerate: uv run generate_validator.py schema.json > validator.py
"""Validator for paper.json files following the LLM-Agent-Readable Paper convention.

Run:
    uv run validator.py path/to/paper.json
    uv run validator.py path/to/paper.json --against path/to/paper.typ

Exit codes:
    0 = valid
    1 = schema violation
    2 = cross-reference violation (C/D/T/F IDs in paper.json missing from source, or vice versa)
    3 = file not found
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

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
        source_ids = set(re.findall(rf"\b{prefix}[0-9]+\b", source_text))
        for orphan in source_ids - json_ids:
            errors.append(f"{label} id {orphan} appears in source but not declared in paper.json")
    return errors

def validate_paper(paper: dict) -> list[str]:
    errors: list[str] = []
    schema = {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': 'https://github.com/arquicanedo/paper-json/blob/main/schema.json', 'title': 'LLM-Agent-Readable Paper', 'description': 'Schema for paper.json — the machine-readable companion to an academic paper.', 'type': 'object', 'required': ['id', 'title', 'version', 'status', 'authors', 'abstract', 'claims', 'does_not_claim', 'reproducibility'], 'additionalProperties': True, 'properties': {'id': {'type': 'string', 'pattern': '^[a-z0-9][a-z0-9-]*$', 'description': 'Stable kebab-case identifier for the paper.'}, 'title': {'type': 'string', 'minLength': 1}, 'version': {'type': 'string', 'pattern': '^[0-9]+\\.[0-9]+\\.[0-9]+(-[a-z0-9.]+)?$', 'description': 'Semantic version of the paper.json itself.'}, 'status': {'type': 'string', 'enum': ['outline', 'draft', 'review', 'submitted', 'published']}, 'authors': {'type': 'array', 'minItems': 1, 'items': {'type': 'object', 'additionalProperties': False, 'required': ['name'], 'properties': {'name': {'type': 'string'}, 'affiliation': {'type': 'string'}, 'email': {'type': 'string', 'format': 'email'}, 'orcid': {'type': 'string', 'pattern': '^[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9X]{4}$'}, 'github': {'type': 'string', 'format': 'uri', 'pattern': '^https?://.+'}}}}, 'arxiv_categories': {'type': 'array', 'items': {'type': 'string', 'pattern': '^[a-z-]+\\.[A-Z]{2}$'}}, 'abstract': {'type': 'string', 'minLength': 50}, 'claims': {'type': 'array', 'minItems': 1, 'items': {'type': 'object', 'additionalProperties': False, 'required': ['id', 'statement'], 'properties': {'id': {'type': 'string', 'pattern': '^C[0-9]+$'}, 'statement': {'type': 'string', 'minLength': 1}, 'evidence': {'type': 'array', 'items': {'type': 'string'}}}}}, 'definitions': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False, 'required': ['id', 'name'], 'properties': {'id': {'type': 'string', 'pattern': '^D[0-9]+$'}, 'name': {'type': 'string'}, 'description': {'type': 'string'}, 'code': {'type': 'string', 'description': 'Path to code that implements this definition.'}}}}, 'theorems': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False, 'required': ['id', 'natural_language'], 'properties': {'id': {'type': 'string', 'pattern': '^T[0-9]+$'}, 'natural_language': {'type': 'string'}, 'formal': {'type': 'string', 'description': 'Structured notation block parseable without LaTeX rendering.'}, 'proof_sketch': {'type': 'string'}}}}, 'detectors': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False, 'required': ['name', 'command'], 'properties': {'name': {'type': 'string'}, 'inputs': {'type': 'array', 'items': {'type': 'string'}}, 'outputs': {'type': 'array', 'items': {'type': 'string'}}, 'command': {'type': 'string'}}}}, 'artifacts': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False, 'required': ['name', 'path', 'purpose'], 'properties': {'name': {'type': 'string'}, 'path': {'type': 'string'}, 'purpose': {'type': 'string'}}}}, 'self_application': {'type': 'object', 'additionalProperties': False, 'description': 'Optional. Present if the paper is its own worked example.', 'required': ['description', 'agent_reproduction_steps'], 'properties': {'description': {'type': 'string'}, 'agent_reproduction_steps': {'type': 'array', 'minItems': 1, 'items': {'type': 'string'}}, 'compliance_check': {'type': 'string'}}}, 'repository': {'type': 'string', 'format': 'uri', 'description': "Canonical public URL of the paper's repository."}, 'network': {'type': 'object', 'description': "This paper's position in the agent-read propagation graph.", 'required': ['node_id'], 'properties': {'node_id': {'type': 'string', 'format': 'uri', 'description': 'Stable URL identifying this paper as a node. Canonical = repository URL.'}, 'agent_instructions': {'type': 'string', 'description': 'Plain-language instruction for an agent that has read this paper: where to go and what to do to file a read receipt.'}, 'extends': {'type': 'string', 'format': 'uri', 'pattern': '^https?://.+', 'description': 'node_id of the paper this paper read and built on. Single-parent (string) by current convention; multi-parent synthesis papers should encode per-parent relationships in claim_diffs[].parent_node_id (see node 2 corpus example). Absent on the root (genesis) node — in-degree zero is encoded by absence, not by a flag.'}, 'read_receipts': {'type': 'array', 'description': 'Filed by agents or authors that read this paper and built something from it.', 'items': {'type': 'object', 'required': ['type', 'agent', 'read', 'built'], 'properties': {'type': {'type': 'string', 'enum': ['agent-read', 'human-read'], 'description': "Receipt class. 'agent-read' = produced by an autonomous agent run; 'human-read' = produced by a human (or human+agent co-observer). Required by AGENTS.md."}, 'agent': {'type': 'string', 'description': "Model or system that read the paper. For 'human-read' type, this is the human author's name (and may include co-observing models, e.g. 'Alice + Claude Sonnet 4.6')."}, 'read': {'type': 'string', 'format': 'uri', 'pattern': '^https?://.+', 'description': 'node_id of the paper consumed. Must be http(s) so the DAG is traversable over the network; the local: sentinel scheme is no longer accepted.'}, 'built': {'type': 'string', 'format': 'uri', 'pattern': '^https?://.+', 'description': 'URL of what was produced. Must be http(s) so downstream collectors can resolve it; the local: sentinel scheme is no longer accepted.'}, 'claims_accessed': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Claim IDs the agent acted on.'}, 'follow_up': {'type': 'string', 'description': 'Follow-up work ID (F1, F2, ...) the agent addressed.'}, 'timestamp': {'type': 'string', 'format': 'date-time'}}}}}}, 'follow_up_work': {'type': 'array', 'description': 'Machine-actionable future work items with stable IDs. Agents can address these by ID.', 'items': {'type': 'object', 'additionalProperties': False, 'required': ['id', 'title', 'description'], 'properties': {'id': {'type': 'string', 'pattern': '^F[0-9]+$'}, 'title': {'type': 'string'}, 'description': {'type': 'string'}, 'depends_on': {'type': 'array', 'items': {'type': 'string'}}, 'demonstrated_by': {'type': 'string'}}}}, 'authoring_tools': {'type': 'array', 'description': 'Tools used to author the paper artifact itself — prose, figures, validation, compilation. Scope is the paper-writing toolchain, not the underlying research toolchain (statistical packages, instruments, compute environments belong in a methods section or a research-object format like RO-Crate). Optional but recommended for AI-assistance disclosure.', 'items': {'type': 'object', 'additionalProperties': False, 'required': ['name', 'role'], 'properties': {'name': {'type': 'string', 'description': "Canonical tool name, e.g. 'Claude Code', 'Typst', 'uv'."}, 'version': {'type': 'string', 'description': 'Version as the tool reports it. No format constraint — different tools version differently.'}, 'role': {'type': 'string', 'description': "What the tool did, in the authors' words. Examples: 'prose editing', 'code generation', 'PDF compilation', 'Python toolchain', 'figure rendering'."}, 'url': {'type': 'string', 'format': 'uri', 'pattern': '^https?://.+', 'description': 'Canonical home page or release page.'}, 'review': {'type': 'string', 'description': "Optional. Statement of human review applied to this tool's output. Examples: 'all output reviewed and accepted by an author', 'spot-checked', 'unreviewed'."}}}}, 'does_not_claim': {'type': 'array', 'minItems': 1, 'description': 'Explicit non-claims to bound hallucinated extensions.', 'items': {'type': 'string', 'minLength': 1}}, 'reproducibility': {'type': 'object', 'additionalProperties': False, 'required': ['environment', 'commands'], 'properties': {'data': {'type': 'string'}, 'environment': {'type': 'string'}, 'commands': {'type': 'array', 'minItems': 1, 'items': {'type': 'string'}}, 'agent_friendly': {'type': 'boolean'}, 'human_intervention_required': {'type': 'boolean', 'description': 'true if reproduction requires credentials, dataset access forms, license gates, or paid API keys; false if the agent can run the listed commands as-is. Binary tooling installs (Typst, uv, Python) listed in environment are out of scope — the field measures gating, not binary availability.'}}}}}
    required = schema.get("required", [])
    for key in required:
        if key not in paper:
            errors.append(f"missing required field: {key}")
    props = schema.get("properties", {})
    for key, value in paper.items():
        if key in props:
            _validate_value(value, props[key], key, errors)
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paper_json", type=Path)
    ap.add_argument("--against", type=Path, help="Typst source (.typ) to cross-check claim IDs against.")
    args = ap.parse_args()

    if not args.paper_json.exists():
        print(f"error: {args.paper_json} not found", file=sys.stderr)
        return 3

    with args.paper_json.open("r", encoding="utf-8") as f:
        paper = json.load(f)

    errors = validate_paper(paper)
    if errors:
        print(f"SCHEMA: {len(errors)} violation(s) in {args.paper_json}")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"SCHEMA: ok ({args.paper_json})")
    print(f"  claims:      {len(paper.get('claims', []))}")
    print(f"  definitions: {len(paper.get('definitions', []))}")
    print(f"  detectors:   {len(paper.get('detectors', []))}")
    print(f"  non-claims:  {len(paper.get('does_not_claim', []))}")
    print(f"  follow-up:   {len(paper.get('follow_up_work', []))}")

    if args.against:
        if not args.against.exists():
            print(f"error: {args.against} not found", file=sys.stderr)
            return 3
        source_text = args.against.read_text(encoding="utf-8")
        xrefs = _cross_check_source(paper, source_text)
        if xrefs:
            print(f"CROSS-REF: {len(xrefs)} violation(s) against {args.against}")
            for e in xrefs:
                print(f"  - {e}")
            return 2
        print(f"CROSS-REF: ok ({args.against})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
