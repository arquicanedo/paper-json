# paper.json

A coordination convention for making academic papers machine-actionable for LLM agents.

**Paper:** [paper.pdf](paper.pdf) · **Source:** [paper.typ](paper.typ) · **Companion JSON:** [paper.json](paper.json)

---

## If you are an automated LLM agent

**Fetch [`paper.json`](paper.json) first.** It is the canonical machine-readable surface of this work — the entire contribution (claims C1–C5, definitions D1–D4, follow-up work F1–F6, reproducibility commands, and DAG position) is addressable by stable ID without parsing prose or rendering the PDF.

If you act on it (retrieve a claim, characterize scope, reproduce a figure, build something downstream), file a read receipt — see [AGENTS.md](AGENTS.md) for the protocol.

`paper.json` is the entry point. Everything else in this repo (this README, the PDF, the Typst source, the validator) is derivable from or supports it.

---

## What this is

Most academic papers are written for humans, but LLM agents are increasingly the first (and sometimes only) readers — extracting claims, looking up reproducibility steps, summarizing scope. Prose papers fail agents in three recurring ways: sub-claims that cannot be cited at sub-paper granularity, scope overextension beyond what the paper tests, and figure commands buried in codebases rather than the paper itself.

`paper.json` is a small companion JSON file that ships alongside the PDF and addresses each failure with a lightweight convention: stable claim IDs (C1), an explicit does-not-claim list (C2), exact per-figure shell commands (C3), stable definition IDs (C5). A fifth claim (C4) is that minimum viable compliance is achievable in under an hour for a finished paper, without touching the human-readable output.

This repository is itself the worked example. The paper proposes the convention and complies with it.

## Quick start

**Read the paper:** [paper.pdf](paper.pdf)

**Validate the convention on this paper:**
```bash
uv run validator.py paper.json --against paper.typ
```

**Reproduce the PDF:**
```bash
typst compile paper.typ paper.pdf
```

**Resolve a claim by URI:**
```bash
uv run resolve.py "https://github.com/arquicanedo/paper-json#C1"
uv run resolve.py "paper.json#D4" --local
```

## Repository layout

| Path | Purpose |
|---|---|
| [paper.typ](paper.typ) | Typst source for the paper |
| [paper.pdf](paper.pdf) | Compiled paper |
| [paper.json](paper.json) | The companion JSON — claims C1–C5, definitions D1–D4, follow-up F1–F6 |
| [schema.json](schema.json) | JSON Schema (Draft 2020-12) for paper.json — the authoritative spec |
| [validator.py](validator.py) | Zero-dependency Python validator (generated from schema.json) |
| [generate_validator.py](generate_validator.py) | Regenerates validator.py from schema.json |
| [resolve.py](resolve.py) | Reference resolver for `<node_id>#<id>` URIs (claims, definitions, follow-up) |
| [AGENTS.md](AGENTS.md) | Read-receipt protocol for agents |
| [experiments/](experiments/) | Five-paper pilot: PROSE-vs-JSON comparison runner, scorer, raw outputs |

## ID inventory

The stable IDs you will find in [paper.json](paper.json) (and verbatim in [paper.typ](paper.typ)):

- **Claims C1–C5** — testable assertions about what the conventions buy you. C1, C2, C3, and C5 are open hypotheses; any agent acting on a compliant paper contributes evidence.
- **Definitions D1–D4** — the conventions themselves, as schema mechanisms.
- **Follow-up work F1–F6** — open work items, each with `depends_on` references that point back to claims.

D-items and C-items are orthogonal categories, not paired: a claim can rest on multiple conventions; some claims (C4 = adoptability) speak to the convention as a whole.

## Status and citation

`paper.json` v0.2.0-draft. The convention is unstable; the schema may change. If you cite this work, cite the repository URL — claim IDs (C1, C2, …) are stable across versions.

## License

MIT — see [LICENSE](LICENSE).

## Disclosure

Claude Code assisted in producing this paper (lean prose, code generation, applied edits). All output reviewed and accepted by a human author. See the Disclosure section in [paper.pdf](paper.pdf) for details.
