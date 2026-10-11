# GitHub Push Plan — antimatter-rabi-ibm

Staged 2026-10-09 by Pip. Decision-agnostic across the A/B/C amend options;
the amend decision gates which manifest gets pushed, nothing else.

## Suggested repo name / visibility

- Name: `antimatter-rabi-ibm` (matches this folder; change freely)
- Handle: `billyrdavis1985-bot` (your GitHub)
- Visibility: **your call** — public like QEC-P1 / quantum-ai-rip, or private.
  The pre-flight's tamper-evident anchor works either way.
- License: **your call** — MIT matches Forge Agent if you want it.

## Push sequence (provenance order)

1. **Amend decision first (A/B/C).** Everything downstream hangs on this.
   - Option A: apply the two corrected fits, re-run sim, regenerate
     FROZEN-MANIFEST.txt, then push **both** manifests — the superseded
     original and the new one — with the amend logged between them.
   - Option B/C: push the existing FROZEN-MANIFEST.txt as-is.
2. **Pre-hardware anchor commit (tonight, before any submission):**
   frozen script, README, OPERATIONS-PLAN, RUN-NIGHT-PREFLIGHT,
   FROZEN-MANIFEST.txt (+ superseded manifest if A). Commit message records
   the UTC timestamp. This is the tamper-evident preregistration anchor —
   push it before the first job leaves the Architect.
3. **Post-run commit(s):** date-tagged raw count CSVs, job IDs, backend
   calibration snapshot, fetch logs. Raw data before analysis, per the
   no-silent-mutation rule.
4. **Analysis commit(s):** fit results, figures, reasoning log. Any
   post-data analysis change is logged as a deviation, not folded in.

## Files to include

- `antimatter_analog_ibm.py`, `README.md`, `OPERATIONS-PLAN.md`,
  `RUN-NIGHT-PREFLIGHT.md`, `FROZEN-MANIFEST.txt`, `.gitignore`
- `REASONING-LOG.md`, `VERIFICATION-fitbias-independent-2026-10-09.md`,
  `selftest-transcript-2026-10-09.txt` — review artifacts, publishable
- `fits-v2-DRAFT.py` — rename or keep; resolve the DRAFT suffix before push
- Raw CSVs / job-ID logs / calibration snapshot — added after the run

## Files excluded (.gitignore)

`.venv/`, `__pycache__/`, `*.env`, anything matching `*token*` /
`*credential*` / `qiskitrc` — no IBM key ever touches the repo.

## Before the first push — quick safety pass

- `git status` shows no secret-like files; `git diff --cached --name-only`
  eyeballed for anything machine-local the .gitignore missed.
