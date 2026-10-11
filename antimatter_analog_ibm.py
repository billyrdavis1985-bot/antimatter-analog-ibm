#!/usr/bin/env python3
"""
antimatter_analog_ibm.py — BASE-antimatter-qubit analog experiments on IBM hardware.

Physics mapping (what transfers and what does not):
  - Antiproton spin-1/2  <->  transmon qubit. Both are driven two-level systems.
    BASE's "coherent quantum transition spectroscopy" IS a Rabi experiment:
    a phase-stable oscillating field driving population between two states.
  - BASE's 50 s spin coherence  <->  T1 / T2-echo on a transmon.
    Same quantities, wildly different substrates and timescales.
  - BASE extracts the g-factor from spin precession frequency  <->
    Ramsey interferometry extracts a frequency offset from fringe frequency.
    Same metrology primitive: frequency estimation via coherent precession.
  - What does NOT transfer: no antimatter on a transmon chip, and on IBM
    hardware the "detuning" is programmed (virtual-Z frame update), not a
    physical Larmor frequency. This reproduces the *protocol* (coherent drive,
    Ramsey, echo) and the *analysis chain* (fringes -> frequency -> precision),
    i.e. a calibration of the measurement chain — the same chain BASE relies on.

Experiments (plain Qiskit, no qiskit_experiments dependency):
  1. Rabi      — Rx(theta) sweep  -> driven oscillation (BASE's core operation)
  2. Ramsey    — pi/2, delay, phase, -pi/2 -> fringe frequency (metrology op)
  3. T1        — X, delay, measure -> energy relaxation
  4. T2 echo   — pi/2, delay/2, X, delay/2, pi/2 -> refocused dephasing

Usage:
  python antimatter_analog_ibm.py sim        # Aer density-matrix sim + selftest
  python antimatter_analog_ibm.py hardware <backend> [rabi|ramsey|t1|all]
                                           # submit jobs to IBM hardware
  python antimatter_analog_ibm.py fetch <job_id> <rabi|ramsey|t1>
                                           # pull counts, run fits, save CSV

Dependencies: qiskit, qiskit-aer, numpy. (qiskit-ibm-runtime only for hardware.)
"""

import sys
import numpy as np

from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, thermal_relaxation_error

# --------------------------------------------------------------------------
# Simulation "device": coherence values in the transmon regime (seconds).
# BASE's antiproton: T2 ~ 50 s. Transmons: T1/T2 ~ 1e-4 s. The *ratio* of
# coherence time to operation time is the interesting comparison — the
# script prints it so the analogy stays quantitative, not hand-wavy.
# --------------------------------------------------------------------------
T1_SIM = 120e-6
T2_SIM = 160e-6          # T2 <= 2*T1, as physics requires
DETUNING_SIM = 250e3     # Hz, programmed Ramsey phase ramp (the "g-factor" proxy)

# Hardware sweep definitions (shared by submit and fetch — keep in sync).
HW_RABI_N = 21
HW_RAMSEY_N, HW_RAMSEY_MAX = 31, 60e-6
HW_T1_N, HW_T1_MAX = 21, 400e-6

BASE_COHERENCE_S = 50.0  # reported antiproton spin coherence time


def run_aer_one(circuit, duration_s, t1=T1_SIM, t2=T2_SIM, shots=4000, seed=7):
    """Run one circuit with thermal relaxation parameterized by its OWN
    idle duration. (Aer does not auto-scale a delay-attached error channel
    with the delay length, so we build the channel per duration. Honest sim.)
    """
    nm = NoiseModel()
    nm.add_all_qubit_quantum_error(
        thermal_relaxation_error(t1, t2, duration_s), ["delay"]
    )
    sim = AerSimulator(method="density_matrix", noise_model=nm,
                       seed_simulator=seed)
    tc = transpile(circuit, sim)
    counts = sim.run(tc, shots=shots).result().get_counts()
    tot = sum(counts.values())
    return counts.get("1", 0) / tot


def rabi_circuits(n_points=41):
    thetas = np.linspace(0, 4 * np.pi, n_points)
    circuits = []
    for th in thetas:
        qc = QuantumCircuit(1, 1)
        qc.rx(th, 0)
        qc.measure(0, 0)
        circuits.append(qc)
    return thetas, circuits


def ramsey_circuit(delay_s, detuning_hz=DETUNING_SIM):
    """Rx(pi/2) -> wait -> virtual-Z phase -> Rx(-pi/2).
    P1 = sin^2(pi * f * d): fringes at the programmed detuning f."""
    qc = QuantumCircuit(1, 1)
    qc.rx(np.pi / 2, 0)
    qc.delay(delay_s, 0, "s")
    qc.rz(2 * np.pi * detuning_hz * delay_s, 0)
    qc.rx(-np.pi / 2, 0)
    qc.measure(0, 0)
    return qc


def t1_circuit(delay_s):
    qc = QuantumCircuit(1, 1)
    qc.x(0)
    qc.delay(delay_s, 0, "s")
    qc.measure(0, 0)
    return qc


def t2_echo_circuit(delay_s):
    """Closing -pi/2: ideal final state is |1>, P1 decays 1 -> 0.5 with dephasing."""
    qc = QuantumCircuit(1, 1)
    qc.rx(np.pi / 2, 0)
    qc.delay(delay_s / 2, 0, "s")
    qc.x(0)
    qc.delay(delay_s / 2, 0, "s")
    qc.rx(-np.pi / 2, 0)
    qc.measure(0, 0)
    return qc


# --------------------------------------------------------------------------
# Fits (numpy only, no scipy dependency)
# --------------------------------------------------------------------------
def fit_exponential(t, y):
    """Fit y = A*exp(-t/T) + B: grid search over B, log-linear (A,T) per
    candidate, keep the triple with the best residual sum of squares.
    The old baseline-from-last-point version underestimated T1 by 22-60%
    on the hardware sweep (decay incomplete at 400 us); fitting B freely
    removes the bias. numpy only, no scipy."""
    t, y = np.asarray(t, dtype=float), np.asarray(y, dtype=float)
    best = None
    for b in np.linspace(min(0.0, y.min() - 0.02), y.min(), 41):
        yy = y - b
        mask = yy > 0
        if mask.sum() < 3:
            continue
        slope, icept = np.polyfit(t[mask], np.log(yy[mask]), 1)
        if slope >= 0:
            continue
        T, A = -1.0 / slope, np.exp(icept)
        rss = np.sum((y - (A * np.exp(-t / T) + b)) ** 2)
        if best is None or rss < best[0]:
            best = (rss, T, A, b)
    if best is None:
        raise RuntimeError("3-param exponential fit failed to converge")
    return best[1]


def fit_cos_frequency(x, y, pad=1024):
    """Dominant frequency via zero-padded FFT of detrended data.
    Zero-padding refines the spectral grid: the raw FFT had 5.0%
    deterministic bin quantization on the 21-point Rabi sweep (and 3.2%
    on Ramsey); padding to 1024 brings both under ~1.5%."""
    yd = y - np.mean(y)
    dx = x[1] - x[0]
    spec = np.abs(np.fft.rfft(yd, n=pad))
    freqs = np.fft.rfftfreq(pad, dx)
    return freqs[np.argmax(spec[1:]) + 1]


def selftest():
    print("== Aer selftest: BASE-analog suite ==")

    # --- Rabi: period must be 2*pi in drive angle -------------------------
    thetas, rcircs = rabi_circuits()
    pr = np.array([run_aer_one(qc, 0.0, seed=1000 + i)
                   for i, qc in enumerate(rcircs)])
    period = 1.0 / fit_cos_frequency(thetas, pr)
    print(f"Rabi period: {period:.3f} rad (expect ~{2*np.pi:.3f})")
    assert abs(period - 2*np.pi) / (2*np.pi) < 0.05, "Rabi period off"

    # --- T1 ----------------------------------------------------------------
    delays = np.linspace(0, 5 * T1_SIM, 25)
    p1 = np.array([run_aer_one(t1_circuit(d), d, seed=2000 + i)
                   for i, d in enumerate(delays)])
    t1_fit = fit_exponential(delays, p1)
    print(f"T1: fit {t1_fit*1e6:.1f} us  (model {T1_SIM*1e6:.0f} us)")
    assert abs(t1_fit - T1_SIM) / T1_SIM < 0.05, "T1 fit off"

    # --- Ramsey: fringe frequency must match the programmed detuning ------
    delays_r = np.linspace(0, 60e-6, 61)
    pram = np.array([run_aer_one(ramsey_circuit(d), d, seed=3000 + i)
                     for i, d in enumerate(delays_r)])
    f_fit = fit_cos_frequency(delays_r, pram)
    print(f"Ramsey detuning: fit {f_fit/1e3:.1f} kHz  (set {DETUNING_SIM/1e3:.0f} kHz)")
    assert abs(f_fit - DETUNING_SIM) / DETUNING_SIM < 0.10, "Ramsey freq off"

    # --- T2 echo: report only (Markovian noise; echo refocuses little) -----
    p2 = np.array([run_aer_one(t2_echo_circuit(d), d, seed=4000 + i)
                   for i, d in enumerate(delays)])
    t2_fit = fit_exponential(delays, p2)
    print(f"T2 echo: fit {t2_fit*1e6:.1f} us  (model T2 {T2_SIM*1e6:.0f} us)")

    # --- The analogy, stated quantitatively --------------------------------
    gate_time = 60e-9  # typical single-qubit gate duration
    ratio_hw = T2_SIM / gate_time
    ratio_base = BASE_COHERENCE_S / 1e-3  # vs ~ms spin-flip timescales
    print("\nCoherent-ops budget (coherence time / operation time):")
    print(f"  transmon (sim): ~{ratio_hw:.0e}   |   BASE antiproton: ~{ratio_base:.0e}")
    print("Both are 'many coherent operations per coherence time' —")
    print("that ratio, not the raw seconds, is what makes a qubit usable.")
    print("\nSELFTEST PASS")


def run_hardware(backend_name, which="all"):
    """which: 'rabi', 'ramsey', 't1', or 'all'. Run the smallest first and
    check your IBM Quantum usage dashboard between jobs — queue time is free,
    only QPU execution time counts against your allocation.

    Uses the V2 Sampler API (qiskit-ibm-runtime >= 1.0; verified against
    0.50.0, where `Sampler` is an alias of `SamplerV2`). V2 samplers are NOT
    context managers — plain instantiation.
    """
    from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2
    service = QiskitRuntimeService()  # uses saved account; token never in code
    backend = service.backend(backend_name)
    dt = backend.target.dt
    print(f"Backend: {backend_name}, dt = {dt*1e9:.2f} ns")
    shots = 4000

    def hw_delay(qc, seconds):
        qc.delay(int(round(seconds / dt)), 0, "dt")

    sampler = SamplerV2(backend)
    if which in ("all", "rabi"):
        thetas, rcircs = rabi_circuits(n_points=HW_RABI_N)
        job = sampler.run(transpile(rcircs, backend), shots=shots)
        print("Rabi job:", job.job_id())

    if which in ("all", "ramsey"):
        hcircs = []
        for d in np.linspace(0, HW_RAMSEY_MAX, HW_RAMSEY_N):
            qc = QuantumCircuit(1, 1)
            qc.rx(np.pi / 2, 0)
            hw_delay(qc, d)
            qc.rz(2 * np.pi * DETUNING_SIM * d, 0)
            qc.rx(-np.pi / 2, 0)
            qc.measure(0, 0)
            hcircs.append(qc)
        job = sampler.run(transpile(hcircs, backend), shots=shots)
        print("Ramsey job:", job.job_id())

    if which in ("all", "t1"):
        tcircs = []
        for d in np.linspace(0, HW_T1_MAX, HW_T1_N):
            qc = QuantumCircuit(1, 1)
            qc.x(0)
            hw_delay(qc, d)
            qc.measure(0, 0)
            tcircs.append(qc)
        job = sampler.run(transpile(tcircs, backend), shots=shots)
        print("T1 job:", job.job_id())
    print("Jobs submitted. Fetch with: fetch <job_id> <rabi|ramsey|t1>")


def fetch(job_id, which):
    """Pull a submitted job's counts and run the fits. Provenance: raw
    probabilities are written to fetch_<job_id>_<which>.csv before analysis."""
    from qiskit_ibm_runtime import QiskitRuntimeService
    service = QiskitRuntimeService()
    job = service.job(job_id)
    print(f"Job {job_id}: status {job.status()}")
    result = job.result()
    n = len(result)
    probs = np.zeros(n)
    for i in range(n):
        counts = result[i].data.c.get_counts()
        tot = sum(counts.values())
        probs[i] = counts.get("1", 0) / tot

    if which == "rabi":
        x = np.linspace(0, 4 * np.pi, HW_RABI_N)
        period = 1.0 / fit_cos_frequency(x, probs)
        print(f"Rabi period: {period:.3f} rad (ideal {2*np.pi:.3f})")
        cols, hdr = (x, probs), "theta_rad,P1"
    elif which == "ramsey":
        x = np.linspace(0, HW_RAMSEY_MAX, HW_RAMSEY_N)
        f = fit_cos_frequency(x, probs)
        print(f"Ramsey detuning: {f/1e3:.2f} kHz "
              f"(programmed {DETUNING_SIM/1e3:.0f} kHz)")
        cols, hdr = (x, probs), "delay_s,P1"
    elif which == "t1":
        x = np.linspace(0, HW_T1_MAX, HW_T1_N)
        t1 = fit_exponential(x, probs)
        print(f"T1: {t1*1e6:.1f} us")
        cols, hdr = (x, probs), "delay_s,P1"
    else:
        raise SystemExit("which must be rabi|ramsey|t1")

    out = f"fetch_{job_id}_{which}.csv"
    np.savetxt(out, np.column_stack(cols), delimiter=",", header=hdr)
    print("raw probabilities ->", out)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "sim"
    if mode == "sim":
        selftest()
    elif mode == "hardware":
        if len(sys.argv) < 3:
            print("usage: python antimatter_analog_ibm.py hardware "
                  "<backend_name> [rabi|ramsey|t1|all]")
            sys.exit(1)
        which = sys.argv[3] if len(sys.argv) > 3 else "all"
        run_hardware(sys.argv[2], which)
    elif mode == "fetch":
        if len(sys.argv) < 4:
            print("usage: python antimatter_analog_ibm.py fetch "
                  "<job_id> <rabi|ramsey|t1>")
            sys.exit(1)
        fetch(sys.argv[2], sys.argv[3])
    else:
        print("unknown mode:", mode)
        sys.exit(1)
