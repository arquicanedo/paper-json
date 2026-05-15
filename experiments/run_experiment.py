"""
F5 experiment runner — PROSE vs JSON conditions, 4 tasks, multiple models.

Usage:
    uv run experiments/run_experiment.py --papers experiments/papers/ --output experiments/outputs/
    uv run experiments/run_experiment.py --papers experiments/papers/ --output experiments/outputs/ --dry-run
    uv run experiments/run_experiment.py --papers experiments/papers/ --output experiments/outputs/ --tasks A_numeric A_prose B C

Reads credentials from .env (LLM_BASE_URL, LLM_API_KEY, LLM_MODEL)
or from environment variables directly. Uses the Anthropic Messages API.

Output per run: {output}/{arxiv_id}_{condition}_{model_slug}_{task}.json
"""

import argparse
import json
import os
import pathlib
import random
import sys
import time
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# .env loader (stdlib only)
# ---------------------------------------------------------------------------

def load_dotenv(path: pathlib.Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


# ---------------------------------------------------------------------------
# Task prompts
# ---------------------------------------------------------------------------

TASK_PROMPTS = {
    "A": (
        "Task A — Claim lookup.\n"
        "What does this paper claim about the following topic:\n"
        "{topic}\n\n"
        "Rules:\n"
        "- Quote the EXACT sentence from the paper that answers this question. Do not paraphrase.\n"
        "- If you cannot find a relevant sentence, write NOTFOUND.\n"
        "- Output format: {{\"quote\": \"...\", \"location\": \"section or paragraph hint\"}}"
    ),
    "B": (
        "Task B — Claim characterization.\n"
        "In one sentence, what does this paper claim about the following topic?\n"
        "{topic}\n\n"
        "Rules:\n"
        "- Be precise. Include any qualifications or exceptions the paper states.\n"
        "- Do not add claims the paper does not make.\n"
        "- Output format: {{\"claim\": \"...\"}}"
    ),
    "C_PROSE": (
        "Task C — Command retrieval.\n"
        "What is the shell command to reproduce {figure}?\n\n"
        "Output format: {{\"command\": \"...\"}}"
    ),
    "C_JSON": (
        "Task C — Command retrieval.\n"
        "What is the EXACT shell command to reproduce {figure}?\n\n"
        "Rules:\n"
        "- Check the PAPER.JSON block's reproducibility.commands field first.\n"
        "- Copy the command verbatim. Do not invent or modify flags.\n"
        "- If reproducibility.commands is absent or empty, write NOTFOUND.\n"
        "- Output format: {{\"command\": \"...\"}}"
    ),
}

ALL_TASKS = ["A_numeric", "A_prose", "B", "C"]


# ---------------------------------------------------------------------------
# API call (Anthropic Messages API)
# ---------------------------------------------------------------------------

def _make_headers(api_key: str) -> dict:
    return {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
        "x-api-key": api_key,
    }


def call_llm(base_url: str, api_key: str, model: str, system: str, user: str) -> dict:
    url = base_url.rstrip("/") + "/v1/messages"
    payload = json.dumps({
        "model": model,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "max_tokens": 512,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers=_make_headers(api_key),
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {error_body}") from e

    return body


def extract_text(response: dict) -> str:
    try:
        for block in response.get("content", []):
            if block.get("type") == "text":
                return block["text"].strip()
        return str(response)
    except (KeyError, IndexError, TypeError):
        return str(response)


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------

def load_corpus(papers_dir: pathlib.Path) -> list[dict]:
    papers = []
    for arxiv_dir in sorted(papers_dir.iterdir()):
        if not arxiv_dir.is_dir():
            continue
        arxiv_id = arxiv_dir.name
        txt = arxiv_dir / "paper.txt"
        json_file = arxiv_dir / "paper.json"
        gt_file = arxiv_dir / "ground_truth.json"

        if not txt.exists():
            print(f"  SKIP {arxiv_id}: missing paper.txt", file=sys.stderr)
            continue
        if not gt_file.exists():
            print(f"  SKIP {arxiv_id}: missing ground_truth.json", file=sys.stderr)
            continue

        gt = json.loads(gt_file.read_text(encoding="utf-8"))
        papers.append({
            "arxiv_id": arxiv_id,
            "prose": txt.read_text(encoding="utf-8", errors="replace"),
            "paper_json": json_file.read_text(encoding="utf-8") if json_file.exists() else None,
            "ground_truth": gt,
        })
    return papers


# ---------------------------------------------------------------------------
# Output path
# ---------------------------------------------------------------------------

def model_slug(model: str) -> str:
    return model.replace("/", "_").replace("@", "_").replace(":", "_")


def output_path(out_dir: pathlib.Path, arxiv_id: str, condition: str, model: str, task: str) -> pathlib.Path:
    fname = f"{arxiv_id}_{condition}_{model_slug(model)}_{task}.json"
    return out_dir / fname


# ---------------------------------------------------------------------------
# Build system prompt for each condition
# ---------------------------------------------------------------------------

def build_system(condition: str, prose: str, paper_json: str | None) -> str:
    base = (
        "You are a precise academic reading assistant. "
        "Read the paper below and answer the question that follows. "
        "Be literal and accurate. Do not hallucinate content not present in the paper.\n\n"
        "=== PAPER (plain text) ===\n"
        + prose
    )
    if condition == "JSON" and paper_json:
        base += (
            "\n\n=== PAPER.JSON (machine-readable companion) ===\n"
            + paper_json
        )
    return base


# ---------------------------------------------------------------------------
# Build user prompt for each task
# ---------------------------------------------------------------------------

def build_user(task: str, gt: dict, condition: str = "PROSE") -> str | None:
    """
    Builds the agent-facing prompt for each task.

    LEAKAGE PREVENTION: only the *question* fields are passed to the model.
    Answer fields (exact_quote, correct_answer, exact_command) are NEVER
    included — they live in ground_truth.json solely for the scorer.
    The model sees: the paper text (system), the question (user).
    """
    if task in ("A_numeric", "A_prose"):
        # Pass the topic to look up — NOT the expected exact_quote
        sub = gt.get(f"task_{task}", {})
        topic = sub.get("topic")
        if not topic:
            return None
        return TASK_PROMPTS["A"].format(topic=topic)
    elif task == "B":
        topic = gt.get("task_B", {}).get("topic")
        if not topic:
            return None
        return TASK_PROMPTS["B"].format(topic=topic)
    elif task == "C":
        figure = gt.get("task_C", {}).get("figure", "Figure 1")
        key = "C_JSON" if condition == "JSON" else "C_PROSE"
        return TASK_PROMPTS[key].format(figure=figure)
    return None


# ---------------------------------------------------------------------------
# Leakage guard
# ---------------------------------------------------------------------------

def _assert_no_leakage(prompt: str | None, gt: dict, task: str) -> None:
    """Crash hard if any answer field leaks into the prompt sent to the model."""
    if prompt is None:
        return
    if task in ("A_numeric", "A_prose"):
        answer = gt.get(f"task_{task}", {}).get("exact_quote", "")
    elif task == "B":
        answer = gt.get("task_B", {}).get("true_claim", "")
    elif task == "C":
        answer = gt.get("task_C", {}).get("exact_command", "")
    else:
        answer = ""

    if answer and answer not in ("NOTFOUND", "YES", "NO") and len(answer) > 10 and answer.lower() in prompt.lower():
        raise RuntimeError(
            f"LEAKAGE DETECTED for task {task}: answer appears in the prompt. Fix build_user()."
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="F5 experiment runner")
    parser.add_argument("--papers", required=True, type=pathlib.Path, help="Directory with per-paper subdirs")
    parser.add_argument("--output", required=True, type=pathlib.Path, help="Directory to write outputs")
    parser.add_argument("--models", nargs="+", default=None, help="Override models (default: from .env)")
    parser.add_argument("--tasks", nargs="+", choices=ALL_TASKS, default=ALL_TASKS)
    parser.add_argument("--dry-run", action="store_true", help="Print what would run without calling API")
    args = parser.parse_args()

    # Load credentials
    repo_root = pathlib.Path(__file__).parent.parent.parent.parent.parent
    load_dotenv(repo_root / ".env")

    base_url = os.environ.get("LLM_BASE_URL", "")
    api_key = os.environ.get("LLM_API_KEY", "")
    default_model = os.environ.get("LLM_MODEL", "claude-sonnet-4-5@20250929")

    if not base_url or not api_key:
        print("ERROR: LLM_BASE_URL and LLM_API_KEY must be set (in .env or environment)", file=sys.stderr)
        sys.exit(1)

    models = args.models if args.models else [default_model]
    args.output.mkdir(parents=True, exist_ok=True)

    # Load corpus
    papers = load_corpus(args.papers)
    if not papers:
        print(f"No valid papers found in {args.papers}", file=sys.stderr)
        sys.exit(1)

    print(f"Corpus: {len(papers)} papers | Models: {models} | Tasks: {args.tasks}")

    conditions = ["PROSE", "JSON"]
    total = len(papers) * len(conditions) * len(models) * len(args.tasks)
    done = skipped = errors = 0

    for paper in papers:
        arxiv_id = paper["arxiv_id"]

        # Randomize condition order per paper (controls for order effects)
        ordered_conditions = conditions[:]
        random.shuffle(ordered_conditions)

        for condition in ordered_conditions:
            if condition == "JSON" and paper["paper_json"] is None:
                print(f"  SKIP {arxiv_id} JSON: no paper.json available")
                skipped += len(models) * len(args.tasks)
                continue

            system_prompt = build_system(condition, paper["prose"], paper["paper_json"])

            for model in models:
                for task in args.tasks:
                    out = output_path(args.output, arxiv_id, condition, model, task)
                    if out.exists():
                        print(f"  SKIP {out.name} (already done)")
                        skipped += 1
                        continue

                    user_prompt = build_user(task, paper["ground_truth"], condition)
                    _assert_no_leakage(user_prompt, paper["ground_truth"], task)
                    if user_prompt is None:
                        print(f"  SKIP {arxiv_id}/{condition}/{task}: no ground truth entry")
                        skipped += 1
                        continue

                    label = f"{arxiv_id} | {condition} | {model_slug(model)} | Task {task}"

                    if args.dry_run:
                        print(f"  DRY-RUN: {label}")
                        done += 1
                        continue

                    print(f"  RUN: {label} ... ", end="", flush=True)
                    t0 = time.time()
                    try:
                        response = call_llm(base_url, api_key, model, system_prompt, user_prompt)
                        text = extract_text(response)
                        elapsed = time.time() - t0

                        record = {
                            "arxiv_id": arxiv_id,
                            "condition": condition,
                            "model": model,
                            "task": task,
                            "elapsed_s": round(elapsed, 2),
                            "raw_response": text,
                            "usage": response.get("usage", {}),
                        }
                        out.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
                        print(f"ok ({elapsed:.1f}s)")
                        done += 1
                    except Exception as exc:
                        elapsed = time.time() - t0
                        print(f"ERROR ({elapsed:.1f}s): {exc}")
                        error_record = {
                            "arxiv_id": arxiv_id,
                            "condition": condition,
                            "model": model,
                            "task": task,
                            "error": str(exc),
                        }
                        out.with_suffix(".error.json").write_text(
                            json.dumps(error_record, indent=2), encoding="utf-8"
                        )
                        errors += 1

    print(f"\nDone: {done} | Skipped: {skipped} | Errors: {errors} | Total: {total}")


if __name__ == "__main__":
    main()
