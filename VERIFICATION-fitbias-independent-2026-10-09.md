# Independent verification of the 2026-10-09 fit-bias pushback

**Date:** 2026-10-09T17:27Z (UTC) · **Verifier:** Pip (independent reproduction, own implementation, did not import `antimatter_analog_ibm.py` or `fits-v2-DRAFT.py`; note: the repro script lived in /tmp and has not persisted — this note is the surviving record of the findings)

## Findings

1. **T1 bias CONFIRMED exactly.** On the noiseless 0–400 µs / 21-pt hardware sweep (constants verified identical in the frozen script, `antimatter_analog_ibm.py` lines 54–56): true T1 = 100/150/200/300 µs fits as **77.0 / 95.5 / 107.3 / 121.1 µs** → biases **−23.0% / −36.3% / −46.4% / −59.6%**. Matches the pushback's "77/96/107/121, −23%..−60%".
2. **Rabi FFT quantization CONFIRMED exactly.** Old FFT-argmax fit: period 6.597 rad vs 6.283 ideal → **+5.00%**, matching the pushback to the digit.
3. **Both fixes CONFIRMED.** 3-param exponential fit → ≤0.21% error on all four noiseless T1 cases. Zero-padded FFT → −1.54% on Rabi (draft docstring claimed ~1.5% median).
4. **Draft harness runs cleanly.** `fits-v2-DRAFT.py` executes; its noisy Monte Carlo (4000 shots, 500 trials, A=0.97/B=0.015) reproduces its own docstring claims: old −22.2%/−36.1%/−46.0%/−59.5%, new ≤0.1%, Rabi 5.00% → 1.54% median. The artifact Billy was told to "run yourself" is executable and honest.

## Refinements for the amend (new, not in the pushback)

5. **Mechanism correction — the bias is structural, not sweep-specific.** The pushback said the sim selftest missed the bug because its sweep runs to 5×T1 "where the decay completes and the baseline assumption holds." Independent check of the exact selftest config (T1_SIM=120 µs, 25 pts, 0–600 µs): it carries **−17.4% bias even noiseless** — exp(−5)=0.67% tail is not zero, and log-linearization amplifies it. The selftest printed −14.0% (shot noise pushed −17.4% up) against a 15% gate. **The fit was biased on BOTH sweeps; the 15% tolerance was simply wider than the sim-sweep bias.** This strengthens the amend case. Implication: the amend should also **tighten the sim T1 gate** (e.g. gate the new 3-param fit at ~5% on both sweep configs).
6. **Ramsey bonus — one fix covers two estimators.** `fit_cos_frequency` is shared by Rabi AND Ramsey. The hardware Ramsey sweep (31 pts, 0–60 µs, programmed 250 kHz detuning) also has FFT bin quantization: **−3.23% noiseless** (bin width 16.13 kHz), fixed to **+0.00%** by zero-padding. Low stakes (programmed quantity, consistency check only), but the single zero-pad fix covers both — one line in the amend.

## Recommendation

Supports **Option A** (amend the fits, re-run sim, rewrite manifest, push new manifest before hardware). Nothing weakens the pushback; the mechanism correction makes it stronger.

## Limits

Analysis code only — no QPU access, no Aer re-run of the full selftest (the −14.0% figure is taken from the pushback message). Billy's decision state was as of 2026-10-09T17:20Z.
