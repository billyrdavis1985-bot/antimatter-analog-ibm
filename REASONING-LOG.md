# Reasoning log — antimatter-analog IBM run (BASE-antimatter-qubit analog)

**Status: DRAFT, pre-run section complete.** To be finalized after data returns.
**NOT part of the frozen preregistration manifest.** Separate comparison artifact for the cross-model council work.
**Script under review:** `antimatter_analog_ibm.py` · sha256 `fe6f257da84bdc16bd3f6f9968d7c2c645c7ec500bfa54207dbf8b0393f95953`
(manifest hash verified against local file 2026-10-09T16:2xZ; selftest transcript
`selftest-transcript-2026-10-09.txt` ran 15:24:41Z, SELFTEST PASS)

---

## 1. Decisions taken (pre-run)

| # | Decision | Why | Alternative rejected |
|---|----------|-----|----------------------|
| 1 | Contained project: Billy + Pip only, no council review | Deliberate departure from his normal council-reviewed workflow; AI-research framing needs a single-reviewer control condition | Full council review (his norm) |
| 2 | No OSF/Zenodo prereg; frozen SHA256 manifest in the operation itself | Keeps containment; hashes + git push give tamper-evidence without a third party | OSF/Zenodo preregistration |
| 3 | Commit + push from the Architect *before* the run as the anchor | Push timestamp is what makes the hashes tamper-evident rather than merely tamper-resistant | Hash-only freeze (tamper-resistant, not tamper-evident) |
| 4 | Run environment: VS Code on the Architect, local venv | Token stays in his secure container, provenance on his disk | Colab-first (rejected: token/provenance hygiene); Colab kept as analysis backup only |
| 5 | Sequence: `sim` selftest → logged-in backend check → `rabi` (hardware smoke test) → meter check → `ramsey` → `t1` | Rabi validates the whole submit→fetch→fit chain before spending budget on the measurement runs | Submitting all jobs at once |
| 6 | Raw probabilities saved to CSV *before* any fitting (`fetch` mode) | His provenance rule: data on disk before analysis touches it | Fit-in-submit (rejected: mixes acquisition and analysis) |
| 7 | Plain-Qiskit experiments, no `qiskit_experiments` dependency | Fewer moving parts, every fit is inspectable numpy | qiskit_experiments (rejected: dependency weight, opaque fits) |
| 8 | Per-duration noise channels in sim (thermal_relaxation_error rebuilt per delay) | Aer does not auto-scale a delay-attached error channel with delay length; single-channel sim would have been silently wrong | One noise model for all delays |

## 2. What I got wrong, and how it got caught

- **V1 API crash (mine, caught pre-run):** the hardware path used `with Sampler(backend) as sampler`.
  qiskit-ibm-runtime 0.50.0 only speaks the V2 API — samplers are not context managers.
  This was a TypeError *before a single shot fired*. Caught in review, script rewritten for
  `SamplerV2` with result extraction via `result[i].data.c.get_counts()`.
- **BASE manuscript numbers (mine, caught pre-run):** I quoted ">80% spin inversions" and "16× linewidth"
  from secondary coverage. Checked against the full *Nature* text: paper says **">70%"** and
  **"more than ten times narrower"** (FWHM < 200 mHz; the 16× was my arithmetic, not their claim).
  Also surfaced from the manuscript: fitted coherence 50.2 ± 4.8 s, accelerator magnetic noise
  alone knocking it to 5.6 s — environment-limited coherence, which is why BASE-STEP matters.
- **Nemo lineage retraction cycle (earlier work):** flagged Mistral/Mistral-NeMo lineage correlation,
  retracted under pushback, re-confirmed with the exact model name. Lesson banked: ask for the exact
  identifier before retracting an evidenced call.

## 3. Independent review findings (Pip, sole-reviewer pass, 2026-10-09 ~16:25Z)

Verified with the local venv against the frozen script. Both findings are in the **analysis code**,
not the acquisition code — they do not affect job submission, only what the fits report.

### 3a. T1 fit carries a -22% to -60% systematic bias on the hardware sweep

`fit_exponential` takes the **last sweep point as the baseline** (`b = y[-1]`), then log-linearizes.
That is only valid when the decay has essentially completed inside the sweep window.
Hardware T1 sweep: 21 points over 0–400 µs. If true T1 is 100–300 µs (the Heron range),
the last point is still 0.07–0.26 of the amplitude above the true floor — so the "baseline"
is biased high and the fitted T1 is biased low. Monte Carlo (4000 shots/point, realistic
readout floor B=0.015, 500 trials per T1):

| true T1 | median fitted T1 | bias |
|---------|-----------------|------|
| 100 µs | 77.9 µs | **-22%** |
| 150 µs | 95.4 µs | **-36%** |
| 200 µs | 107.5 µs | **-46%** |
| 300 µs | 119.9 µs | **-60%** |

The signature was already in the selftest transcript and went unremarked:
"T1: fit 103.2 us (model 120 us)" is a **-14% error on noiseless-ish sim data** —
almost entirely this systematic, not shot noise (the gate is 15%, so it passed at 14%).

Why it matters: the T1 number feeds the coherent-ops-budget ratio, which is the entire
quantitative content of the BASE analogy ("the ratio, not the raw seconds, is what makes
a qubit usable"). A -60% T1 corrupts the headline comparison.

**Fix (verified, no extra QPU cost):** 3-parameter fit — grid search over B, log-linear
for (A, T) at each B, keep the best-RSS triple. Same Monte Carlo: bias **≤ 0.1%** at all
four T1 values. See `fits-v2-DRAFT.py`.

### 3b. Rabi period from the 21-point FFT has a deterministic 5.0% bin quantization

`fit_cos_frequency` takes the argmax FFT bin with no sub-bin refinement. 21 points over
0–4π puts the true 2π-period signal nearest to a bin edge: noiseless estimate is
6.597 rad vs 6.283 ideal — **+5.0%, deterministic, shot noise does not move it**
(500 trials at 4000 shots: median error exactly 5.0%).
The printed "Rabi period: X.XXX rad" overstates what the estimator can deliver.

Why it matters less: rabi is the smoke test (submit→fetch→fit chain), not a measurement.
5% is fine for a smoke test — but the three printed decimals are not honest.

**Fix (verified, no extra QPU cost):** zero-padded FFT (21 pts → 1024) for sub-bin
resolution. Same Monte Carlo: median error **1.5%**, p95 2.5%. (Parabolic interpolation
around the peak was tried first and made it *worse* — 5.45% — so it was discarded;
kept in the record as a rejected alternative.) See `fits-v2-DRAFT.py`.

## 4. Open decision for Billy (pre-run, time-sensitive)

The findings landed **after** the manifest was frozen (15:24:13Z) and the selftest passed.
The script on disk is unchanged and hash-verified. Options:

- **A. Amend and re-freeze:** apply the two fixed fits, re-run `sim`, rewrite the manifest,
  commit + push the new manifest before any hardware submission. Cost: ~10 minutes.
  My recommendation — the bias was found *pre-run*, and his own stopping rule says
  reopen when a result could change the wording or the decision. A known 20–60% systematic
  on the headline number is exactly that.
- **B. Run as-is, pre-declare the bias:** push the current manifest, run tonight, and carry
  the quantified bias table above as a known systematic into the post-run analysis —
  corrected there, logged as a deviation. Weaker: deviations are for things discovered
  *after* seeing data, not before.
- **C. Run as-is, uncorrected:** not recommended, recorded here so the rejection is explicit.

Whichever is chosen: **do not edit `antimatter_analog_ibm.py` after the manifest commit+push.**
The push is the anchor; a post-push edit silently breaks the chain the prereg exists to create.

## 5. Post-run section (to be completed after data returns)

- [ ] Job IDs, backend(s) actually used, queue vs execution time vs the 40-min budget
- [ ] Rabi smoke-test outcome: did submit→fetch→fit hold end to end?
- [ ] Ramsey fringe frequency vs programmed 250 kHz detuning
- [ ] T1 vs the bias table above (which correction, if any, was applied)
- [ ] Deviations from OPERATIONS-PLAN.md, logged as deviations, not silent edits
- [ ] What the data changed in this log (per the stopping rule)
