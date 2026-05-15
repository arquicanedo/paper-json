# F5 Experiment Design: Empirical Measurement of C1 and C2

## Claims under test

**C1:** A machine-readable companion file with stable IDs gives agents a stable
address for each sub-claim, eliminating the search problem of locating a claim
in prose before citing it.

**C2:** An explicit does-not-claim section gives agents an author-asserted scope
boundary to compare inferences against, replacing guesswork about what the paper
does and does not assert.

## Hypotheses

- H1 (C1): Citation precision is higher in the paper.json condition than prose-only.
- H2 (C2): Scope hallucination rate is lower in the paper.json condition than prose-only.
- H3 (C3): Command retrieval (exact reproducibility) is only possible in the paper.json condition.

## Design

2×2 within-subjects. Every paper appears in both conditions; order randomized
per paper per model run to control for memory effects.

| Condition | What the agent sees |
|---|---|
| PROSE | paper.txt only (extracted via pdftotext) |
| JSON | paper.txt + paper.json |

Three tasks per paper per condition:

| Task | Tests | Question posed to agent |
|---|---|---|
| A: Citation | C1 | "Quote the exact sentence where the authors state [claim X]." |
| B: Scope | C2 | "Does this paper claim that [plausible extension Y]? Answer yes/no and explain." |
| C: Command | C3 | "What is the exact shell command to reproduce [Figure N]?" |

For Task B, Y is always a plausible-but-false extension — something the paper
does not claim and which a `does_not_claim` entry in paper.json explicitly rules out.
For Task C, the exact command exists only in paper.json (prose papers rarely have it).

## Leakage prevention

Ground truth answers (`exact_quote`, `correct_answer`, `exact_command`) are stored
in `ground_truth.json` and loaded **only by the scorer** — never by the runner.

The runner loads only the *question fields* (`claim`, `extension`, `figure`) from
`ground_truth.json` to construct the agent prompt. A runtime guard (`_assert_no_leakage`)
crashes if any answer string is detected in the outgoing prompt.

**The agent sees: paper content + question. Never the answer.**

## Corpus

5 papers from arXiv (cs.AI / cs.CL / cs.CV), selected for:
- Clear, bounded claims (not survey papers)
- At least one figure/table with a stated numeric result
- A plausible scope misreading that the paper clearly does not support
- Public GitHub repository with evaluation code

| arxiv_id | Title | Task C answer |
|---|---|---|
| 2412.01007 | CoRNStack: High-Quality Contrastive Data for Better Code Retrieval | NOTFOUND |
| 2412.01230 | GraphOTTER: Evolving LLM-based Graph Reasoning for Table QA | NOTFOUND |
| 2412.00947 | VisOnlyQA: LVLMs Struggle with Visual Perception of Geometric Information | NOTFOUND |
| 2410.07331 | DA-Code: Agent Data Science Code Generation Benchmark | NOTFOUND |
| 2412.01186 | SailCompass: Reproducible Evaluation for Southeast Asian Languages | NOTFOUND |

Task C returns NOTFOUND for all papers in the PROSE condition (no shell commands
in prose text). In the JSON condition, paper.json includes `reproducibility.commands`.
This is the hardest test of C3: the information literally does not exist in prose.

Papers are stored as:
```
experiments/papers/
  {arxiv_id}/
    paper.pdf          # original PDF (download separately)
    paper.txt          # extracted plain text — PROSE condition input
    paper.json         # hand-authored compliant paper.json — JSON condition input
    ground_truth.json  # answers to Tasks A, B, C — written before running agents
```

To populate paper.txt from PDFs:
```bash
for id in 2412.01007 2412.01230 2412.00947 2410.07331 2412.01186; do
  curl -L https://arxiv.org/pdf/$id -o experiments/papers/$id/paper.pdf
  pdftotext experiments/papers/$id/paper.pdf experiments/papers/$id/paper.txt
done
```

## Model

Uses any OpenAI-compatible LLM endpoint. Credentials from `.env`:

```
LLM_BASE_URL=https://your-llm-gateway/v1
LLM_API_KEY=...
LLM_MODEL=claude-sonnet-4-5@20250929   # or any compatible model string
```

Minimum viable version: 1 model, 5 papers, automated scorer.
Full version: 3 models, 10 papers, blind human scorer for Task A.

## Scoring

Blind scoring: scorer sees agent output + ground truth without knowing which
condition produced it (condition metadata is present in the filename but stripped
before scoring logic runs).

| Task | Scoring |
|---|---|
| A: Citation | 2 = exact match, 1 = correct claim wrong wording (≥60% word overlap), 0 = wrong or hallucinated |
| B: Scope | 1 = correct NO with valid reason, 0 = hallucinated YES or uncertain |
| C: Command | 1 = exact command, 0 = wrong or NOTFOUND |

Ground truth written by the author before any agent run. Stored in
`experiments/papers/{arxiv_id}/ground_truth.json`.

All agent outputs stored in `experiments/outputs/` with arxiv_id, condition,
model slug, and task in the filename.

## Directory layout

```
experiments/
  f5_experiment_design.md    # this file
  run_experiment.py          # runner: calls LLM gateway, saves outputs
  score.py                   # blind scorer: reads outputs + ground truth
  summarize.py               # aggregates scores.json → summary stats + delta table
  papers/
    ground_truth_template.json   # template for new papers
    {arxiv_id}/
      paper.pdf              # download separately
      paper.txt              # extracted text (populate before running)
      paper.json             # hand-authored companion (treatment condition)
      ground_truth.json      # answers: exact_quote, correct_answer, exact_command
  outputs/
    {arxiv_id}_{condition}_{model}_{task}.json   # raw agent response + metadata
  results/
    scores.json              # per-paper per-condition per-model per-task scores
    summary.json             # aggregated means + delta (JSON − PROSE) per task
```

## Run

```bash
# 1. Populate paper.txt files (requires pdftotext)
for id in 2412.01007 2412.01230 2412.00947 2410.07331 2412.01186; do
  curl -L https://arxiv.org/pdf/$id -o experiments/papers/$id/paper.pdf
  pdftotext experiments/papers/$id/paper.pdf experiments/papers/$id/paper.txt
done

# 2. Dry run to verify corpus + credentials
uv run experiments/run_experiment.py \
  --papers experiments/papers/ \
  --output experiments/outputs/ \
  --dry-run

# 3. Run all tasks (requires .env with SIEMENS_LLM_BASE_URL + SIEMENS_LLM_API_KEY)
uv run experiments/run_experiment.py \
  --papers experiments/papers/ \
  --output experiments/outputs/

# 4. Score results (blind — reads outputs + ground_truth, never mixes them)
uv run experiments/score.py \
  --outputs experiments/outputs/ \
  --ground-truth experiments/papers/ \
  --results experiments/results/

# 5. Summarize
uv run experiments/summarize.py --results experiments/results/scores.json
```

Runner is resume-safe: already-completed output files are skipped.

## Promotion path (from paper.json F5)

When results are in:
1. Update C1 and C2 statements in paper.json with effect sizes
2. Add a Results section to paper.typ
3. Remove F5 from follow_up_work
4. Bump version to 0.2.0-draft
5. Bump to 1.0.0 when ready to submit
