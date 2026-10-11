# Antimatter-Qubit Analog on IBM Hardware

Runs the BASE experiment's *protocol* — not its particle — on IBM quantum
hardware via the cloud.

## The mapping

| BASE (CERN, antiproton) | This script (transmon) |
|---|---|
| Spin-1/2 two-level system | Qubit |
| Coherent drive (phase-stable RF) | Rx(theta) microwave pulse |
| 50 s spin coherence | T1 / T2-echo |
| g-factor from precession frequency | Detuning from Ramsey fringes |
| Linewidth -> measurement precision | Fringe fit -> frequency estimate |

What does NOT transfer: no antimatter on the chip; the "detuning" is a
programmed virtual-Z phase, not a physical Larmor frequency. This is a
calibration of the *measurement chain* — the same chain BASE relies on.

## Run it

```bash
./.venv/bin/python antimatter_analog_ibm.py sim                              # verified Aer simulation
./.venv/bin/python antimatter_analog_ibm.py hardware <backend> [rabi|ramsey|t1|t2|all]
./.venv/bin/python antimatter_analog_ibm.py fetch <job_id> <rabi|ramsey|t1|t2>
```

`sim` runs a selftest: Rabi period, T1 fit, Ramsey detuning recovery, T2 echo.
All four pass (fits recover the programmed noise-model values).

`hardware` needs your IBM Quantum account saved (`QiskitRuntimeService.save_account`)
and a backend name from your account. `"all"` submits the frozen set
(rabi+ramsey+t1); `t2` is opt-in (added in amend B).

## Results (ibm_fez, Heron r2 — 2026-10-10/11)

| Experiment | Result | Note |
|---|---|---|
| Rabi | period 6.187 rad (ideal 2π) | −1.53%, matches predicted estimator quantization (−1.54%) to the digit |
| Ramsey | detuning 225.59 kHz (programmed 250 kHz) | −9.8%; consistency check, logged as real deviation (dephasing on a below-average qubit) |
| T1 (n=4) | 113.2 ± 23.0 µs | three reps cluster 124.7 ± 1.1 µs; first (78.7) an outlier — transpiler qubit-pick variation, logged |
| T2 echo | 111.1 µs | T2/T1 ≈ 0.89, healthy dephasing regime |

**Coherent-ops budget (measured T2):** 111.1 µs / 60 ns ≈ **1.9×10³** gate
operations per coherence time, vs BASE's antiproton ≈ 5×10⁴. Same qualitative
regime — many coherent ops per coherence time — at a smaller budget. The
ratio, not the raw seconds, is the analogy's payload.

Full per-run details: `RESULTS-2026-10-11.md`. Raw counts: `fetch_*.csv`,
committed before analysis.

## Provenance

- Frozen SHA256 manifests committed before hardware (`FROZEN-MANIFEST*.txt`;
chain: original → amend A → amend B, all preserved).
- Amend A: fixed T1 fit bias (3-param exponential) and FFT bin quantization
(zero-padded), tightened sim gate 15%→5%. Amend B: added T2-echo hardware path.
- Sim selftest passes identically on two machines (Aer).
- Repeats sample the transpiler's best-available qubit per submission —
typical hardware variation, not one qubit's drift.

## Files

- `antimatter_analog_ibm.py` — the suite (numpy + qiskit + qiskit-aer only)
- `fetch_*.csv` — raw measurement counts, one file per job
- `RESULTS-2026-10-11.md` — run summary with job IDs and analysis
- `FROZEN-MANIFEST*.txt` — hash-frozen code manifests and amend chain
- `OPERATIONS-PLAN.md`, `RUN-NIGHT-PREFLIGHT.md`, `REASONING-LOG.md`,
`VERIFICATION-fitbias-independent-2026-10-09.md` — planning and review docs
