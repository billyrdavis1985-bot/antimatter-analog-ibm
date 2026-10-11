# Antimatter-Qubit Analog on IBM Hardware

Runs the BASE experiment's *protocol* — not its particle — on IBM quantum
hardware via the cloud.

> **Correction notice (2026-10-11):** a post-hoc review found analysis errors
> that change several published numbers and withdraw the BASE ops-budget
> comparison. The frozen script is unchanged. Corrected results are below;
> full details and reproduction are in [`ERRATA-2026-10-11.md`](ERRATA-2026-10-11.md).

## The mapping

| BASE (CERN, antiproton) | This script (transmon) |
|---|---|
| Spin-1/2 two-level system | Qubit |
| Coherent drive (phase-stable RF) | Rx(theta) gate (compiled as virtual-Z around fixed √X pulses: a phase sweep, not an amplitude sweep) |
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
Rabi, T1 and Ramsey are gated pass/fail; T2 echo is reported but not gated.
Note: the selftest uses its own sweep grids, not the hardware grids (see ERRATA §6).

`hardware` needs your IBM Quantum account saved (`QiskitRuntimeService.save_account`)
and a backend name from your account. `"all"` submits the frozen set
(rabi+ramsey+t1); `t2` is opt-in (added in amend B).

## Install (fresh clone)

**Requires Python 3.12 or newer.** The numpy pin (2.5.3) does not install on
3.11 or older.

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

**Windows (PowerShell):** the commands are the same with Windows paths. Use
`py -3.12 -m venv .venv` to create the venv, then `.venv\Scripts\pip.exe` in place
of `./.venv/bin/pip` and `.venv\Scripts\python.exe` in place of `./.venv/bin/python`.
Put the `pip install` arguments on one line, since `\` does not continue lines in
PowerShell.

## Repo structure

```
antimatter-analog-ibm/
├── antimatter_analog_ibm.py      # the suite: sim, hardware submit, fetch+fit (single file by design —
│                                 # one SHA256 covers the entire frozen protocol)
├── README.md                     # this file
├── LICENSE                       # MIT
├── RESULTS-2026-10-11.md         # run summary: job IDs, numbers as first reported
├── ERRATA-2026-10-11.md          # post-hoc corrections (read this with RESULTS)
├── reanalysis/
│   ├── reanalyze_posthoc.py      # re-fits the raw CSVs; frozen vs corrected, side by side
│   ├── reanalysis-2026-10-11.json  # its full output
│   ├── recover_qubits.py         # physical qubit + IBM calibration per job (no QPU time)
│   └── qubit-map.csv             # its output: which qubit each job ran on
├── FROZEN-MANIFEST.txt            # SHA256 of the frozen script (amend B current)
├── FROZEN-MANIFEST-SUPERSEDED-2026-10-11-amendA.txt   # amend A manifest (fit fixes)
├── FROZEN-MANIFEST-SUPERSEDED-2026-10-09.txt          # original manifest
├── OPERATIONS-PLAN.md            # experiment plan and run order
├── RUN-NIGHT-PREFLIGHT.md        # pre-run checklist
├── REASONING-LOG.md              # decisions, alternatives, what went wrong
├── VERIFICATION-fitbias-independent-2026-10-09.md     # independent fit-bias audit
├── selftest-transcript-2026-10-09.txt                 # sim selftest, ORIGINAL script (superseded)
├── selftest-transcript-2026-10-11-amendB.txt          # sim selftest, current amend-B script
├── PUSH-PLAN.md                  # repo push mechanics
├── .gitignore                    # venv, caches, credentials — never committed
└── fetch_<job_id>_<exp>.csv      # measured P1 per sweep point (4,000 shots each),
                                  # one file per IBM job, committed before analysis
```

Design note: the single-file script and hardcoded sweep constants are
deliberate — the frozen SHA256 anchors code *and* experimental parameters
together. Splitting either would split the provenance.

## Results (ibm_fez, Heron r2 — 2026-10-10/11, corrected 2026-10-11)

Corrected values come from `reanalysis/reanalyze_posthoc.py` (weighted nonlinear
fits with ±1σ, run on the committed raw data). The originally published values
are kept for the record. Why each one changed: `ERRATA-2026-10-11.md`.

| Experiment | Corrected | As first published | Note |
|---|---|---|---|
| Rabi | 6.284 ± 0.007 rad | 6.187 rad | Recovers 2π. The earlier −1.53% was an estimator artifact. End-to-end plumbing test, not an amplitude Rabi. |
| Ramsey (qubit 70) | qubit frame offset \|δ\| = 22.5 ± 0.4 kHz (sign undetermined); T2\* ≈ 39 µs | 225.59 kHz, "dephasing" | Sweep sampled exactly at Nyquist (250 kHz). The offset is a real physical frequency measurement. |
| T1, qubit 6 (n=3) | 108–125 µs (model-dependent) | 124.7 ± 1.1 µs | IBM's calibration: 133.9 µs. Single exponential fits poorly (reduced χ² 9–12). |
| T1, qubit 70 (n=1) | 74–79 µs | 78.7 µs, "outlier" | Different qubit confirmed from job records; not an outlier. IBM: 95.6 µs. |
| T2 echo, qubit 70 (n=2) | 85.9 ± 3.0 µs | pooled 109.2 µs | Matches IBM's 84.4 µs; frozen estimator read high. |
| T2 echo, qubit 6 (n=1) | 94–111 µs | pooled 109.2 µs | IBM: 121.1 µs. |

Physical qubits per job are in `reanalysis/qubit-map.csv`. The originally published
T1 (n=4) and T2 (n=3) averages mixed two qubits and are withdrawn.

**Coherent-ops budget:** about 3.6–3.9×10³ for the transmon (T2 echo per qubit
over IBM's reported 24 ns sx gate). The comparison to BASE is **withdrawn**. The *Nature*
paper's Rabi frequency (~50 mHz) and 16 s drive time put BASE at a few coherent
operations per coherence time, not 5×10⁴. BASE's figure of merit is linewidth
from long interrogation, not operation count.

Per-run details as first reported: `RESULTS-2026-10-11.md`. Raw data: `fetch_*.csv`,
committed before analysis.

## Provenance

- The script was frozen and committed before any hardware submission (`656d3c3`,
amend A, sha `3921c0d5…`). The manifest files (`FROZEN-MANIFEST*.txt`; chain
original → amend A → amend B) were committed later, at `7af9fca`, after the run.
Their hashes match the files they list, except README.md, which has changed since.
- Amend A: fixed T1 fit bias (3-param exponential) and FFT bin quantization
(zero-padded), tightened sim gate 15%→5%. Amend B: added T2-echo hardware path.
- Sim selftest passes on the current script from a clean venv with the pins above
(`selftest-transcript-2026-10-11-amendB.txt`).
- The physical qubit per job was not recorded at run time. It was recovered afterwards
from IBM's job records (`reanalysis/recover_qubits.py`, no QPU time) and is committed
as `reanalysis/qubit-map.csv`.
- Post-hoc corrections are logged as deviations in `ERRATA-2026-10-11.md`; the frozen
script is never edited after freeze.
