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

## Install (fresh clone)

```bash
python -m venv .venv
./.venv/bin/pip install "qiskit==2.5.2" "qiskit-aer==0.17.2" \
    "qiskit-ibm-runtime==0.50.0" "numpy==2.5.3" "scipy==1.18.1"
```

Then save your IBM Quantum credentials (once — the token lives in
`~/.qiskit/`, never in this repo):

```bash
./.venv/bin/python -c "from qiskit_ibm_runtime import QiskitRuntimeService; \
    QiskitRuntimeService.save_account(channel='ibm_quantum_platform', token='YOUR_TOKEN')"
```

Get the token from your IBM Quantum Platform account settings. Verify with
`./.venv/bin/python antimatter_analog_ibm.py sim` — expect `SELFTEST PASS`.

## Repo structure

```
antimatter-analog-ibm/
├── antimatter_analog_ibm.py      # the suite: sim, hardware submit, fetch+fit (single file by design —
│                                 # one SHA256 covers the entire frozen protocol)
├── README.md                     # this file
├── LICENSE                       # MIT
├── RESULTS-2026-10-11.md         # run summary: job IDs, numbers, analysis
├── FROZEN-MANIFEST.txt            # SHA256 of the frozen script (amend B current)
├── FROZEN-MANIFEST-SUPERSEDED-2026-10-11-amendA.txt   # amend A manifest (fit fixes)
├── FROZEN-MANIFEST-SUPERSEDED-2026-10-09.txt          # original manifest
├── OPERATIONS-PLAN.md            # experiment plan and run order
├── RUN-NIGHT-PREFLIGHT.md        # pre-run checklist
├── REASONING-LOG.md              # decisions, alternatives, what went wrong
├── VERIFICATION-fitbias-independent-2026-10-09.md     # independent fit-bias audit
├── selftest-transcript-2026-10-09.txt                 # sim selftest output
├── PUSH-PLAN.md                  # repo push mechanics
├── .gitignore                    # venv, caches, credentials — never committed
└── fetch_<job_id>_<exp>.csv      # raw measurement counts, one file per IBM job,
                                  # committed before analysis
```

Design note: the single-file script and hardcoded sweep constants are
deliberate — the frozen SHA256 anchors code *and* experimental parameters
together. Splitting either would split the provenance.

## Results (ibm_fez, Heron r2 — 2026-10-10/11)

| Experiment | Result | Note |
|---|---|---|
| Rabi | period 6.187 rad (ideal 2π) | −1.53%, matches predicted estimator quantization (−1.54%) to the digit |
| Ramsey | detuning 225.59 kHz (programmed 250 kHz) | −9.8%; consistency check, logged as real deviation (dephasing on a below-average qubit) |
| T1 (n=4) | 113.2 ± 23.0 µs | three reps cluster 124.7 ± 1.1 µs; first (78.7) an outlier — transpiler qubit-pick variation, logged |
| T2 echo (n=3) | 109.2 ± 11.8 µs | T2/T1 ≈ 0.88, healthy dephasing regime |

**Coherent-ops budget (measured T2):** 109.2 µs / 60 ns ≈ **1.8×10³** gate
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
