# Operations Plan — antimatter-analog IBM run, night of 2026-10-09

Target: ibm_fez (first choice; ibm_marrakesh as alternate). Budget: ~40 of 141 IBM minutes.

## 1. Failure-point review (done before any code runs)

| # | Failure point | Status |
|---|---|---|
| 1 | Hardware path used `with Sampler(backend) as sampler` (V1 pattern). In qiskit-ibm-runtime 0.50.0, `Sampler` is an alias of `SamplerV2`, which is **not** a context manager — this would have raised `TypeError` on the first hardware call tonight. | **FIXED & verified** by inspecting the installed 0.50.0 package. Hardware path rewritten for V2: plain instantiation, `sampler.run([circuits], shots=...)`. |
| 2 | V1 result extraction (`job.result().get_counts()`) does not exist in V2. | **FIXED & verified**: `job.result()[i].data.c.get_counts()` tested against a local V2 sampler (Aer's), P1 recovered correctly. New `fetch` mode pulls any submitted job, runs the fits, writes raw CSV. |
| 3 | Sim bugs from last night (fixed then): correlated simulator seeds across sweep points, log(0) baseline in the exponential fit, flipped echo closing pulse, delay-duration noise not auto-scaling in Aer. | **FIXED**; `sim` selftest passes (Rabi 2π, T1 ≈ model, Ramsey = programmed detuning). |
| 4 | `save_account` channel. | **Verified**: `channel="ibm_quantum"` is valid in 0.50.0. |
| 5 | End-to-end hardware submission. | **Cannot verify from here** — needs your credentials, which stay in your container. Mitigation: smoke-test with the smallest job (`rabi`) first; if submission or fetch breaks, everything stops and we diagnose before spending more budget. |

**Re-copy the script to the Architect** — the hardware path changed since last night's version.

## 2. Environment decision: VS Code on the Architect, local venv

- **VS Code + local venv on the Architect (recommended).** Matches your QEC-P1 workflow; provenance files (job IDs, CSVs, calibration snapshots) land on your disk; your token stays in your container and is typed once into `save_account`; no session timeouts while jobs sit in the queue. Use native Windows Python or WSL2 — whichever QEC-P1 ran under. Consistency beats novelty.
- **Colab (backup only).** Works (`pip install`, `save_account` each session), and it's fine for the *analysis* step later. Not for the run: weaker secrets handling by your standards, sessions can die during queue waits, provenance needs Drive mounting.
- Plain terminal is fine too, but VS Code's integrated terminal + file view is the practical choice for a run night.

Setup (once): `python -m venv .venv`, `pip install qiskit qiskit-aer qiskit-ibm-runtime`,
then `QiskitRuntimeService.save_account(channel="ibm_quantum", token="...")` with the
token from your container. Then `python antimatter_analog_ibm.py sim` must print SELFTEST PASS
before anything touches hardware.

## 3. Run sequence (tonight)

1. `sim` → SELFTEST PASS. If it fails, stop — environment problem, not a hardware problem.
2. Logged-in check: IBM Quantum dashboard → Compute Resources → confirm ibm_fez status is operational. Note the calibration timestamp.
3. `hardware ibm_fez rabi` → record job ID → check usage dashboard (expect a small fraction of a minute).
4. `fetch <job_id> rabi` → confirm Rabi period ≈ 2π. This validates the entire submit→fetch→fit chain on real hardware.
5. `hardware ibm_fez ramsey` → `fetch` → detuning should recover the programmed 250 kHz.
6. `hardware ibm_fez t1` → `fetch` → T1 in the ~100 µs regime; compare against the backend's calibration T1.
7. Optional: `hardware ibm_marrakesh all` — same protocol, second chip; both then sit alongside your QEC-P1 numbers.

## 4. If things fail

- **Job fails / backend errors:** check backend status page first; don't resubmit blindly into an outage.
- **Fits look wrong on hardware:** re-run the fit functions against `sim` output first. If sim fits and hardware doesn't, it's device physics (or a bad calibration window), not the analysis.
- **Budget alarm:** stop after `rabi`. The chain validation is the valuable part; ramsey/t1 can wait for another night.
- **Anything unexpected:** save the raw counts CSV first, then diagnose. Raw data is never re-generated from memory.
