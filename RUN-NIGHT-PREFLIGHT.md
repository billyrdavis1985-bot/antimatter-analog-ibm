# Pre-flight: antimatter-analog IBM run (ibm_fez / ibm_marrakesh)

Budget: ~40 of your 141 IBM minutes. Estimate for the full suite is a
conservative **2–3 min of QPU time** (73 circuits × 4,000 shots; T1 sweep
delays sum to ~4.2 ms/shot, Ramsey ~0.9 ms/shot, rep-delay ~0.25 ms/shot;
queue time is free). Nowhere near the cap — re-runs are affordable.

## Setup (once)

1. `pip install qiskit qiskit-aer qiskit-ibm-runtime` in a venv
2. `QiskitRuntimeService.save_account(channel="ibm_quantum", token="...")`
   — token from your container, typed there, never pasted anywhere near me
3. Run `sim` first to confirm the environment (selftest: Rabi period ~2π,
   T1 fit ~120 µs, Ramsey ~250 kHz)
4. Confirm backend status (see platform-status note below) before submitting

## Run order (smallest first, check the meter)

1. `hardware ibm_fez rabi` — check IBM Quantum usage dashboard after this job
2. `hardware ibm_fez ramsey`
3. `hardware ibm_fez t1`
4. Optional: `hardware ibm_marrakesh all` — same protocol, second chip;
   both chips then sit alongside your QEC-P1 numbers

## Provenance to record (your standards)

- Job IDs from the script output, backend name, and the backend's
  calibration snapshot (T1/T2 per qubit are in the QEC-P1 comparison set)
- Commit the raw counts + fit outputs with a date tag before any analysis
- Keep BASE numbers cited to the manuscript (below), not the coverage

## The comparison anchors — manuscript numbers (corrected 2026-10-09)

Last night's deep dive pulled these from secondary coverage. The *Nature*
abstract (Latacz et al., Nature 644, 64–68 (2025), DOI
10.1038/s41586-025-09323-1) states them more conservatively:

| Quantity | Secondary coverage (last night) | Manuscript (use this) |
|---|---|---|
| Spin coherence | ~50 s | > 50 s (talk slides: 50.2 ± 4.8 s) |
| Spin-inversion probability | > 80% | **> 70%** |
| Resonance FWHM | 200 mHz, "16× narrower" | **< 200 mHz, "more than ten times narrower"** |
| Measurement goal | parts-per-trillion CPT test | fractional accuracy **< 100 ppt** on the magnetic moments |
| FWHM limit (current) | — | cyclotron-frequency measurement noise |

The 16× figure is arithmetic (3.2 Hz 2017 linewidth ÷ 0.2 Hz); the paper's
own claim is the conservative >10×. Cite the manuscript.

## The honest boundary (unchanged)

No antimatter on the chip; the "detuning" is a programmed virtual-Z phase,
not a physical Larmor frequency. What transfers: the protocol (coherent
drive → fringes → frequency → precision) and the analysis chain. The ratio
worth comparing: your coherence-to-gate ratio vs. BASE's 50 s.

## Optional follow-up (after run 1 validates the chain)

Same suite on a Heron you haven't touched — cross-chip comparison of
coherence-to-gate ratios. One variable changes (the chip), the protocol
stays frozen. Preregister it before running.

## Platform status

Checked 2026-10-09 ~09:25 EDT (logged out, guest): no announced outage,
degraded service, or scheduled maintenance for IBM Quantum today or this
weekend. IBM Cloud Status (cloud.ibm.com/status) shows "All systems
operational" for Quantum Compute with no incidents any day Sep 10 – Oct 9;
recent Quantum announcements (Oct 2, Sep 2) are feature news, not outages.
Per-backend status (ibm_fez / ibm_marrakesh specifically) requires login —
confirm on the Compute Resources page before submitting tonight.
