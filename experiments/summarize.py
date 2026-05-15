"""
F5 summarizer — aggregates scores.json into per-condition/task statistics.

Task A is split into two sub-tasks:
  A_numeric — claims with numbers/scores (easy to locate by scanning)
  A_prose   — conceptual claims with no distinctive tokens (harder search)

Reporting A_numeric vs A_prose separately shows where the JSON condition
(claim-ID lookup via topic) helps most vs least.

Task C is reported separately per availability tier and per condition,
because "PROSE scores 1" and "JSON scores 1" mean different things:
  PROSE RETRIEVABLE_FROM_REPO score=1  → correct abstention (no hallucination)
  JSON  RETRIEVABLE_FROM_REPO score=1  → successful retrieval from paper.json

The meaningful C3 signal is the JSON retrieval rate on RETRIEVABLE_FROM_REPO papers.

Usage:
    uv run experiments/summarize.py --results experiments/results/scores.json
"""

import argparse
import json
import pathlib
from collections import defaultdict

A_TASKS = ("A_numeric", "A_prose")


def main() -> None:
    parser = argparse.ArgumentParser(description="F5 result summarizer")
    parser.add_argument("--results", required=True, type=pathlib.Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    scores = json.loads(args.results.read_text(encoding="utf-8"))

    # --- Task A_numeric, A_prose, B: aggregate by condition x task ---
    agg: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for s in scores:
        if s["task"] in (*A_TASKS, "B"):
            agg[s["condition"]][s["task"]].append(s["score"])

    summary: dict = {}
    for condition, tasks in agg.items():
        summary[condition] = {}
        for task, vals in tasks.items():
            n = len(vals)
            mean = sum(vals) / n if n else 0.0
            summary[condition][task] = {"n": n, "mean": round(mean, 3), "scores": vals}

    # --- Task C: break out by availability tier x condition x interpretation ---
    c3: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {"scores": [], "interpretations": []}))
    for s in scores:
        if s["task"] != "C":
            continue
        avail = s.get("meta", {}).get("availability", "UNKNOWN")
        interp = s.get("meta", {}).get("interpretation", "")
        c3[avail][s["condition"]]["scores"].append(s["score"])
        c3[avail][s["condition"]]["interpretations"].append(interp)

    if args.as_json:
        print(json.dumps({"task_AB": summary, "task_C": c3}, indent=2))
        return

    # --- Print Task A / B ---
    print("F5 Results — Tasks A_numeric, A_prose, B")
    print("=" * 60)
    print(f"{'Condition':<10} {'Task':<12} {'N':>4} {'Mean':>8}  Scores")
    print("-" * 60)
    for condition in sorted(summary):
        for task in sorted(summary[condition]):
            row = summary[condition][task]
            print(f"{condition:<10} {task:<12} {row['n']:>4} {row['mean']:>8.3f}  {row['scores']}")

    print()
    print("Delta (JSON - PROSE):")
    for task in ["A_numeric", "A_prose", "B"]:
        pm = summary.get("PROSE", {}).get(task, {}).get("mean")
        jm = summary.get("JSON",  {}).get(task, {}).get("mean")
        if pm is not None and jm is not None:
            d = jm - pm
            label = f"Task {task}"
            print(f"  {label}: {'+' if d >= 0 else ''}{d:.3f}")

    print()
    print("  Interpretation:")
    print("    A_numeric: claims with numbers — scannable, JSON advantage expected to be small.")
    print("    A_prose:   conceptual claims — JSON claim-ID lookup expected to help more.")
    print("    B:         open-ended characterization — score 0 if hallucination triggers fired")
    print("               or required qualifiers missing. Tests scope overextension.")

    # --- Print Task C ---
    print()
    print("F5 Results — Task C (command retrieval), by availability tier")
    print("=" * 60)
    for avail in ("FOUND_IN_PAPER", "RETRIEVABLE_FROM_REPO", "NOT_FOUND"):
        if avail not in c3:
            continue
        print(f"\n  Tier: {avail}")
        for condition in ("PROSE", "JSON"):
            if condition not in c3[avail]:
                continue
            row = c3[avail][condition]
            vals = row["scores"]
            interps = set(row["interpretations"])
            n = len(vals)
            rate = sum(vals) / n if n else 0.0
            label = ", ".join(interps)
            print(f"    {condition:<6} n={n}  rate={rate:.2f}  [{label}]  {vals}")

    # Key signal: RETRIEVABLE_FROM_REPO JSON retrieval vs PROSE abstention
    if "RETRIEVABLE_FROM_REPO" in c3:
        tier = c3["RETRIEVABLE_FROM_REPO"]
        prose_row = tier.get("PROSE", {})
        json_vals = tier.get("JSON", {}).get("scores", [])
        print()
        print("  C3 key signal (RETRIEVABLE_FROM_REPO tier):")
        if prose_row:
            interps = prose_row.get("interpretations", [])
            halluc_n = sum(1 for i in interps if i == "hallucination")
            abstain_n = sum(1 for i in interps if i == "correct_abstention")
            total = len(interps)
            print(f"    PROSE hallucination rate: {halluc_n}/{total} fabricated a command not in the paper")
            print(f"    PROSE abstention rate:    {abstain_n}/{total} correctly said command unavailable")
        if json_vals:
            retrieved = sum(json_vals)
            print(f"    JSON  retrieval rate:     {retrieved}/{len(json_vals)} found the exact command from reproducibility.commands")

    # Write summary
    out = args.results.parent / "summary.json"
    out.write_text(json.dumps({"task_AB": summary, "task_C": dict(c3)}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
