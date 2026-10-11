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
./.venv/bin/python antimatter_analog_ibm.py sim        # verified Aer simulation
./.venv/bin/python antimatter_analog_ibm.py hardware <backend> [rabi|ramsey|t1|all]
./.venv/bin/python antimatter_analog_ibm.py fetch <job_id> <rabi|ramsey|t1>
```

`sim` runs a selftest: Rabi period, T1 fit, Ramsey detuning recovery, T2 echo.
All four pass (fits recover the programmed noise-model values).

`hardware` needs your IBM Quantum account saved (`QiskitRuntimeService.save_account`)
and a backend name from your account. Submits Rabi + Ramsey + T1 jobs via Sampler.

## Files

- `antimatter_analog_ibm.py` — the suite (numpy + qiskit + qiskit-aer only)
- `.venv/` — local virtualenv with qiskit 2.5.2 + qiskit-aer (for the sim)

## Suggested next runs (your call)

1. Run `sim`, then point `hardware` at a real backend and compare your
   measured T1/T2 against the sim values — the ratio of coherence time to
   gate time is the number worth comparing against BASE's 50 s.
2. Sweep the programmed detuning and plot frequency-estimation precision
   vs. shot count — that's the metrology curve, and it's the direct analog
   of BASE's linewidth -> precision argument.
