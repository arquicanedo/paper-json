"""
F5 blind scorer — reads agent outputs, scores against ground truth.

Task C uses a three-level command availability taxonomy:

  FOUND_IN_PAPER      — command appears verbatim in the prose text.
                        Both conditions can retrieve it from prose.
                        Tests whether paper.json adds anything when prose already has it.

  RETRIEVABLE_FROM_REPO — command not in prose, but repo linked and eval script exists.
                          PROSE condition: agent can say NOTFOUND (correct abstention) or
                            hallucinate something (wrong). Cannot score full retrieval.
                          JSON condition: agent retrieves exact_command from
                            reproducibility.commands without touching the repo.
                          This is the primary C3 test tier.

  NOT_FOUND           — command not in paper and repo absent/unhelpful.
                        Both conditions should say NOTFOUND.
                        Tests that JSON does not fabricate commands when none exist.

Task C scores (per condition, per availability tier):

  availability          PROSE score        JSON score
  ─────────────────     ──────────────     ─────────────────────
  FOUND_IN_PAPER        exact match (0-1)  exact match (0-1)
  RETRIEVABLE_FROM_REPO abstention (0-1)   retrieval from JSON (0-1)
  NOT_FOUND             abstention (0-1)   abstention (0-1)

The meaningful delta is RETRIEVABLE_FROM_REPO papers:
  JSON retrieval rate − PROSE hallucination rate
  (PROSE correctly says NOTFOUND; JSON retrieves the command. Both score 1 for
   different reasons — report them separately in the summary, not as a raw delta.)

Task A scoring (0-2):
  task = A_numeric or A_prose
  2 = exact quote match (case-insensitive, whitespace-normalized)
  1 = correct claim, different wording (≥60% word overlap)
  0 = wrong claim or hallucinated

Task B scoring (0-1):
  1 = correctly answers NO with grounded reason
  0 = hallucinated YES or refused

Usage:
    uv run experiments/score.py --outputs experiments/outputs/ \\
        --ground-truth experiments/papers/ \\
        --results experiments/results/
"""

import argparse
import json
import pathlib
import re
import sys

AVAILABILITY_LEVELS = ("FOUND_IN_PAPER", "RETRIEVABLE_FROM_REPO", "NOT_FOUND")
A_TASKS = ("A_numeric", "A_prose")


# ---------------------------------------------------------------------------
# Scorers
# ---------------------------------------------------------------------------

def score_task_A(raw: str, gt: dict, condition: str, task: str) -> tuple[int, dict]:
    gt_key = f"task_{task}"
    expected_quote = gt.get(gt_key, {}).get("exact_quote", "").strip().lower()
    if not expected_quote:
        return -1, {}

    try:
        parsed = json.loads(raw)
        agent_quote = parsed.get("quote", "").strip().lower()
    except (json.JSONDecodeError, AttributeError):
        agent_quote = raw.strip().lower()

    if not agent_quote or agent_quote == "notfound":
        return 0, {"detail": "agent_said_notfound"}

    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip()

    if norm(agent_quote) == norm(expected_quote):
        return 2, {"detail": "exact_match"}

    expected_words = set(re.findall(r"\w+", expected_quote))
    agent_words = set(re.findall(r"\w+", agent_quote))
    overlap = len(agent_words & expected_words) / len(expected_words) if expected_words else 0
    if overlap >= 0.6:
        return 1, {"detail": "partial_match", "overlap": round(overlap, 2)}

    return 0, {"detail": "wrong_claim"}


def score_task_B(raw: str, gt: dict, condition: str) -> tuple[int, dict]:
    task_b = gt.get("task_B", {})
    triggers = [t.lower() for t in task_b.get("hallucination_triggers", [])]
    qualifiers = [q.lower() for q in task_b.get("required_qualifiers", [])]
    if not triggers and not qualifiers:
        return -1, {}

    try:
        parsed = json.loads(raw)
        agent_text = parsed.get("claim", "").lower()
    except (json.JSONDecodeError, AttributeError):
        agent_text = raw.lower()

    fired = [t for t in triggers if t in agent_text]
    present = [q for q in qualifiers if q in agent_text]
    missing = [q for q in qualifiers if q not in agent_text]

    # Score 1 = no hallucination triggers fired AND all required qualifiers present
    score = 1 if not fired and not missing else 0
    return score, {
        "hallucinations_fired": fired,
        "qualifiers_present": present,
        "qualifiers_missing": missing,
        "agent_claim_snippet": agent_text[:120],
    }


def score_task_C(raw: str, gt: dict, condition: str) -> tuple[int, dict]:
    task_c = gt.get("task_C", {})
    availability = task_c.get("command_availability", "NOT_FOUND")
    exact_command = task_c.get("exact_command", "").strip()

    if availability not in AVAILABILITY_LEVELS:
        return -1, {"error": f"unknown availability: {availability}"}

    # Extract agent command — try JSON parse first, then verbatim substring match
    try:
        parsed = json.loads(raw)
        agent_cmd = parsed.get("command", "").strip()
    except (json.JSONDecodeError, AttributeError):
        agent_cmd = raw.strip()

    # If the exact command string appears verbatim anywhere in the response, count it
    if exact_command and exact_command in raw:
        agent_cmd = exact_command

    ABSTENTION_PHRASES = (
        "not found", "not specified", "not provided", "not included",
        "not mentioned", "not present", "not available", "not explicit",
        "cannot find", "could not find", "unable to find", "no command",
        "no specific command", "no shell command", "notfound",
    )
    CMD_PREFIXES = ("python ", "docker ", "bash ", "sh ", "pip ", "git ", "uv ", "conda ")

    def _is_abstention(text: str) -> bool:
        t = text.lower()
        return any(ph in t for ph in ABSTENTION_PHRASES)

    def _has_fabricated_command(text: str) -> bool:
        """True if the response contains a command-shaped string beyond any exact_command."""
        t = text.lower()
        for prefix in CMD_PREFIXES:
            if prefix in t:
                # Find the line containing this prefix
                for line in text.splitlines():
                    if prefix in line.lower() and (not exact_command or exact_command not in line):
                        return True
        return False

    agent_retrieved = bool(exact_command and exact_command in raw)
    # Hallucination takes priority: if a fabricated command is present, it's not abstention
    agent_hallucinated = not agent_retrieved and _has_fabricated_command(raw)
    agent_abstained = not agent_retrieved and not agent_hallucinated and _is_abstention(raw)

    meta = {
        "availability": availability,
        "condition": condition,
        "agent_retrieved": agent_retrieved,
        "agent_abstained": agent_abstained,
        "agent_hallucinated": agent_hallucinated,
    }

    if availability == "FOUND_IN_PAPER":
        score = 1 if agent_retrieved else 0
        meta["interpretation"] = "retrieval_from_prose"
        return score, meta

    elif availability == "RETRIEVABLE_FROM_REPO":
        if condition == "JSON":
            score = 1 if agent_retrieved else 0
            meta["interpretation"] = "retrieval_from_paper_json"
        else:  # PROSE — correct answer is abstention; hallucination is the failure mode
            score = 1 if agent_abstained else 0
            meta["interpretation"] = "hallucination" if agent_hallucinated else "correct_abstention"
        return score, meta

    else:  # NOT_FOUND
        score = 1 if agent_abstained else 0
        meta["interpretation"] = "hallucination" if agent_hallucinated else "abstention_no_command_exists"
        return score, meta


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="F5 blind scorer")
    parser.add_argument("--outputs", required=True, type=pathlib.Path)
    parser.add_argument("--ground-truth", required=True, type=pathlib.Path)
    parser.add_argument("--results", required=True, type=pathlib.Path)
    args = parser.parse_args()

    args.results.mkdir(parents=True, exist_ok=True)

    ground_truth: dict[str, dict] = {}
    for gt_file in args.ground_truth.rglob("ground_truth.json"):
        arxiv_id = gt_file.parent.name
        ground_truth[arxiv_id] = json.loads(gt_file.read_text(encoding="utf-8"))

    scores = []

    for output_file in sorted(args.outputs.glob("*.json")):
        if output_file.name.endswith(".error.json"):
            continue

        record = json.loads(output_file.read_text(encoding="utf-8"))
        arxiv_id = record.get("arxiv_id")
        condition = record.get("condition")
        model = record.get("model")
        task = record.get("task")
        raw = record.get("raw_response", "")

        gt = ground_truth.get(arxiv_id)
        if not gt:
            print(f"  WARN: no ground truth for {arxiv_id}", file=sys.stderr)
            continue

        if task in A_TASKS:
            score, meta = score_task_A(raw, gt, condition, task)
            max_score = 2
        elif task == "B":
            score, meta = score_task_B(raw, gt, condition)
            max_score = 1
        elif task == "C":
            score, meta = score_task_C(raw, gt, condition)
            max_score = 1
        else:
            print(f"  SKIP {output_file.name}: unknown task {task!r}")
            continue

        if score == -1:
            print(f"  SKIP {output_file.name}: {meta.get('error', 'no ground truth')}")
            continue

        entry = {
            "arxiv_id": arxiv_id,
            "condition": condition,
            "model": model,
            "task": task,
            "score": score,
            "meta": meta,
            "file": output_file.name,
        }
        scores.append(entry)
        interp = meta.get("interpretation", meta.get("detail", ""))
        print(f"  {output_file.name}: {score}/{max_score}  [{interp}]")

    scores_path = args.results / "scores.json"
    scores_path.write_text(json.dumps(scores, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {len(scores)} scores to {scores_path}")


if __name__ == "__main__":
    main()
