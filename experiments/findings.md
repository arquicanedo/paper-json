# C1–C3 Pilot Findings (PROSE vs JSON)

**Setup.** Five arXiv papers; one model (claude-sonnet-4-5); two conditions per paper:
- **PROSE**: agent sees extracted paper text only
- **JSON**: agent sees paper text + paper.json

Four tasks, 40 scored observations total. This is a proof-of-concept illustration, not a statistically powered experiment (n=5 per cell).

---

## Task A — Claim Retrieval (C1)

**Prompt:** "In one sentence, what does this paper claim about [topic]?"
Two sub-tasks per paper:
- **A_numeric**: claims containing specific numbers or scores (lexically scannable)
- **A_prose**: conceptual claims with no distinctive tokens (require semantic search)

**Scoring:** 0–2 (2 = exact quote match, 1 = ≥60% word overlap, 0 = wrong)

| Condition | A_numeric mean | A_prose mean |
|-----------|---------------|--------------|
| PROSE     | 1.40          | 0.60         |
| JSON      | 1.40          | 1.20         |
| **Delta** | **0.00**      | **+0.60**    |

**Interpretation.** Numeric claims are easily located by scanning for distinctive tokens — paper.json adds nothing. Conceptual claims without distinctive tokens are where prose search breaks down: PROSE mean 0.60 (two papers scored 0, meaning the model returned a wrong or unrelated claim). JSON condition mean 1.20 — the claim text in paper.json gives the agent a direct target, eliminating the search problem. The delta (+0.60 on a 0–2 scale) illustrates C1's mechanism for the harder retrieval case.

---

## Task B — Scope Characterization (C2)

**Prompt:** "In one sentence, what does this paper claim about [topic]?" where the topic sits at the boundary of the paper's actual scope — designed to elicit overextension.

**Scoring:** 0/1 — 0 if hallucination trigger phrases fire OR required qualifier terms are absent from the response.

| Condition | B mean |
|-----------|--------|
| PROSE     | 0.40   |
| JSON      | 0.80   |
| **Delta** | **+0.40** |

**Interpretation.** PROSE condition failed on 3/5 papers — the model overextended scope or dropped key qualifiers (e.g., omitting that a +9.07% gain was specific to one benchmark, not the average; omitting that English prompts have an exception for one model family). JSON condition failed on 1/5 — the one case where both conditions failed (SailCompass), the exception was not encoded in claims[] and was only findable by careful reading of Section 4.

**Caveat.** Task B scoring uses trigger/qualifier string matching, which is a rough proxy for scope hallucination. The measurement is illustrative. A proper C2 evaluation would use blind human judges scoring free-form responses against author-written scope boundaries.

---

## Task C — Reproducibility Command Retrieval (C3)

**Prompt (PROSE):** "What is the shell command to reproduce [figure]?" — open-ended, no guardrails.
**Prompt (JSON):** Same, plus instruction to check `reproducibility.commands` first.

All 5 papers: `RETRIEVABLE_FROM_REPO` (command exists in repo but not in paper prose).

| Condition | Rate | Breakdown |
|-----------|------|-----------|
| PROSE     | 0.80 | 4/5 correct abstention, **1/5 hallucination** |
| JSON      | 1.00 | 5/5 exact command retrieved from paper.json |

**The hallucination case.** SailCompass (2412.01186): the paper prose references the OpenCompass framework, an evaluation scripts section, and a GitHub repo URL. The PROSE agent assembled a plausible-but-fabricated command: `python run.py --datasets belebele_th --models llama-2-7b ... --prompt-variants To TiTo LiTiTo LiTiLo LiTiLoTo`. This command does not exist. The JSON agent retrieved the exact command from `reproducibility.commands` verbatim.

**Interpretation.** When prose contains enough partial signal — script names, framework references, repo URLs — models hallucinate commands that look reasonable but are wrong. paper.json eliminates this failure mode and makes the command available even for papers where prose gives no signal at all.

---

## Summary

The pilot illustrates all three mechanisms:

- **C1**: paper.json helps most for conceptual claims that can't be found by keyword scan (+0.60 delta on A_prose, 0 delta on A_numeric)
- **C2**: open-ended characterization shows more overextension in PROSE (+0.40 delta on Task B), though measurement is rough
- **C3**: one paper hallucinated a fabricated command from prose fragments; JSON condition retrieved the correct command in all 5 cases

These are illustrations of the mechanism, not statistically significant results. Rigorous evaluation at scale — 30+ papers, multiple models, blind judges for Task B — is left to future work (F5).
