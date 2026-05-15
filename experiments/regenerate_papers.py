"""Regenerate paper.pdf and paper.txt for each experiments/papers/<arxiv_id>/.

The experiment runner reads paper.txt for the PROSE condition. The PDFs and
extracted text files are not committed to this repository (see
experiments/papers/LICENSE_NOTICE.md). Run this script after a fresh clone, or
whenever you want to refresh the local cache.

Reads each paper.json's arxiv_id field, fetches the PDF from arxiv.org, and
extracts text via pdftotext (poppler).

Requirements:
    - curl (for arxiv download)
    - pdftotext (poppler-utils): apt install poppler-utils
                                 brew install poppler
                                 winget install poppler

Run:
    uv run experiments/regenerate_papers.py
    uv run experiments/regenerate_papers.py --only 2412.01230
    uv run experiments/regenerate_papers.py --force   # re-fetch even if cached

Exit codes:
    0 = all papers regenerated (or already cached)
    1 = a fetch or extraction failed
    2 = pdftotext or curl not found
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


PAPERS_DIR = Path(__file__).resolve().parent / "papers"


def check_dependencies() -> None:
    missing = []
    for cmd in ("curl", "pdftotext"):
        if shutil.which(cmd) is None:
            missing.append(cmd)
    if missing:
        print(f"error: missing required tools: {', '.join(missing)}", file=sys.stderr)
        print("  install poppler-utils for pdftotext (apt / brew / winget)", file=sys.stderr)
        sys.exit(2)


def discover_papers(only: str | None) -> list[tuple[str, Path]]:
    """Return [(arxiv_id, paper_dir), ...] from each paper.json's arxiv_id field."""
    out = []
    for paper_json in sorted(PAPERS_DIR.glob("*/paper.json")):
        try:
            obj = json.loads(paper_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"warn: {paper_json} is not valid JSON: {e}", file=sys.stderr)
            continue
        arxiv_id = obj.get("arxiv_id")
        if not arxiv_id:
            print(f"warn: {paper_json} has no arxiv_id field, skipping", file=sys.stderr)
            continue
        if only and arxiv_id != only:
            continue
        out.append((arxiv_id, paper_json.parent))
    return out


def fetch_pdf(arxiv_id: str, dest: Path, force: bool) -> bool:
    if dest.exists() and not force:
        print(f"  cached: {dest.name}")
        return True
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    print(f"  fetch:  {url} -> {dest.name}")
    rc = subprocess.run(
        ["curl", "-L", "--fail", "--silent", "--show-error", "-o", str(dest), url],
    ).returncode
    if rc != 0:
        print(f"  error:  curl failed for {url}", file=sys.stderr)
        return False
    return True


def extract_text(pdf: Path, txt: Path, force: bool) -> bool:
    if txt.exists() and not force:
        print(f"  cached: {txt.name}")
        return True
    print(f"  extract: {pdf.name} -> {txt.name}")
    rc = subprocess.run(["pdftotext", str(pdf), str(txt)]).returncode
    if rc != 0:
        print(f"  error:  pdftotext failed for {pdf}", file=sys.stderr)
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="Regenerate only this arxiv_id")
    ap.add_argument("--force", action="store_true", help="Re-fetch and re-extract even if files exist")
    args = ap.parse_args()

    check_dependencies()

    papers = discover_papers(args.only)
    if not papers:
        print("error: no papers found", file=sys.stderr)
        return 1

    failed: list[str] = []
    for arxiv_id, paper_dir in papers:
        print(f"=== {arxiv_id} ===")
        pdf = paper_dir / "paper.pdf"
        txt = paper_dir / "paper.txt"
        if not fetch_pdf(arxiv_id, pdf, args.force):
            failed.append(arxiv_id)
            continue
        if not extract_text(pdf, txt, args.force):
            failed.append(arxiv_id)
            continue

    if failed:
        print(f"\nfailed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"\nok: {len(papers)} paper(s) ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
