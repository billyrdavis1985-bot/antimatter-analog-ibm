#!/usr/bin/env python3
"""
reanalyze_posthoc.py — POST-HOC reanalysis of the ibm_fez raw data (2026-10-11).

This is a logged deviation, NOT part of the frozen protocol. The frozen script
(antimatter_analog_ibm.py, sha256 a5ab9f53…) is untouched and remains the record
of what was preregistered. This file re-fits the same committed CSVs with
weighted nonlinear least squares and reports both estimators side by side, so
every correction in ERRATA-2026-10-11.md can be reproduced from raw data.

Usage (from repo root, inside the README venv):
    ./.venv/bin/python -I reanalysis/reanalyze_posthoc.py            # fits + checks
    ./.venv/bin/python -I reanalysis/reanalyze_posthoc.py --json out.json

Needs numpy + scipy. Imports the frozen estimators from the frozen script for
the side-by-side column (needs qiskit/qiskit-aer, as in the README install).
"""

import argparse
import glob
import importlib.util
import json
import os
import sys

import numpy as np
from scipy.optimize import curve_fit

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FROZEN = os.path.join(REPO, "antimatter_analog_ibm.py")
SHOTS = 4000                 # per circuit, all ibm_fez jobs (RESULTS-2026-10-11.md)
CHI2_FLAG = 3.0              # reduced chi^2 above this: model inadequate, say so
GATE_TIME_ASSUMED = 60e-9    # same assumption as the frozen script; NOT measured


def load_frozen():
    spec = importlib.util.spec_from_file_location("frozen", FROZEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_csv(path):
    d = np.loadtxt(path, delimiter=",")
    return d[:, 0], d[:, 1]


def job_id(path):
    # fetch_<job_id>_<kind>.csv
    return os.path.basename(path)[len("fetch_"):].rsplit("_", 1)[0]


def binomial_sigma(p, shots=SHOTS):
    # Floor avoids zero weight at P1 = 0 or 1.
    return np.sqrt(np.clip(p * (1 - p), 1.0 / shots, None) / shots)


def wfit(model, x, y, p0, **kw):
    """Weighted NLLS. Returns params, 1-sigma errors (inflated by
    sqrt(reduced chi^2) when it exceeds 1), reduced chi^2, RSS."""
    sig = binomial_sigma(y)
    p, cov = curve_fit(model, x, y, p0=p0, sigma=sig, absolute_sigma=True,
                       maxfev=50000, **kw)
    resid = y - model(x, *p)
    dof = len(x) - len(p)
    chi2r = float(np.sum((resid / sig) ** 2) / dof)
    err = np.sqrt(np.diag(cov)) * np.sqrt(max(chi2r, 1.0))
    return p, err, chi2r, float(np.sum(resid ** 2))


def expdec(t, A, T, B):
    return A * np.exp(-t / T) + B


def ramsey_model(t, A, f, phi, T2s, B):
    return A * np.exp(-t / T2s) * np.cos(2 * np.pi * f * t + phi) + B


def rabi_model(x, A, P, phi, B):
    return A * np.cos(2 * np.pi * x / P + phi) + B


def group(vals):
    v = np.asarray(vals, dtype=float)
    return {"mean": float(v.mean()), "sd": float(v.std(ddof=1)) if len(v) > 1 else None,
            "n": int(len(v))}


def analyze(frozen):
    out = {"deviation": "post-hoc reanalysis, not preregistered", "shots": SHOTS}

    # ---- T1 and T2 echo -------------------------------------------------
    for kind in ("t1", "t2"):
        rows = []
        for path in sorted(glob.glob(os.path.join(REPO, f"fetch_*_{kind}.csv"))):
            t, y = load_csv(path)
            (A, T, B), (sA, sT, sB), chi2r, _ = wfit(
                expdec, t, y, [y[0] - y[-1], 100e-6, y[-1]])
            rows.append({
                "job": job_id(path),
                "frozen_fit_us": frozen.fit_exponential(t, y) * 1e6 if frozen else None,
                "nlls_us": T * 1e6, "nlls_err_us": sT * 1e6,
                "floor_B": B, "red_chi2": chi2r,
                "single_exp_adequate": chi2r <= CHI2_FLAG,
            })
        out[kind] = {"runs": rows,
                     "nlls_group_us": group([r["nlls_us"] for r in rows]),
                     "frozen_group_us": group([r["frozen_fit_us"] for r in rows])
                     if frozen else None}

    # ---- Ramsey -----------------------------------------------------------
    path = glob.glob(os.path.join(REPO, "fetch_*_ramsey.csv"))[0]
    d, y = load_csv(path)
    step = d[1] - d[0]
    nyq = 1 / (2 * step)
    prog = frozen.DETUNING_SIM if frozen else 250e3
    branches = []
    for f0 in (prog - 25e3, prog + 25e3):   # one start on each side of Nyquist
        p, e, chi2r, rss = wfit(ramsey_model, d, y, [-0.45, f0, 0.0, 40e-6, 0.5])
        branches.append({"f_khz": p[1] / 1e3, "f_err_khz": e[1] / 1e3,
                         "T2star_us": p[3] * 1e6, "T2star_err_us": e[3] * 1e6,
                         "red_chi2": chi2r, "rss": rss})
    offs = [abs(b["f_khz"] - prog / 1e3) for b in branches]
    out["ramsey"] = {
        "job": job_id(path), "programmed_khz": prog / 1e3,
        "sample_step_us": step * 1e6, "nyquist_khz": nyq / 1e3,
        "at_nyquist": bool(np.isclose(nyq, prog)),
        "frozen_fft_khz": frozen.fit_cos_frequency(d, y) / 1e3 if frozen else None,
        "alias_branches": branches,
        "aliases_indistinguishable": bool(np.isclose(branches[0]["rss"],
                                                     branches[1]["rss"], rtol=1e-6)),
        "frame_offset_abs_khz": float(np.mean(offs)),
        "frame_offset_err_khz": branches[0]["f_err_khz"],
    }

    # ---- Rabi ---------------------------------------------------------------
    path = glob.glob(os.path.join(REPO, "fetch_*_rabi.csv"))[0]
    x, y = load_csv(path)
    p, e, chi2r, _ = wfit(rabi_model, x, y, [-0.5, 2 * np.pi, 0.0, 0.5])
    out["rabi"] = {"job": job_id(path),
                   "frozen_fft_rad": 1 / frozen.fit_cos_frequency(x, y) if frozen else None,
                   "nlls_period_rad": p[1], "nlls_err_rad": e[1],
                   "ideal_rad": 2 * np.pi, "red_chi2": chi2r,
                   "note": "Rx(theta) compiles to virtual-Z around fixed sqrt(X) "
                           "pulses: a gate-phase sweep, not a drive-amplitude Rabi."}

    # ---- Coherent-ops budget (transmon side only) -------------------------
    t2 = out["t2"]["nlls_group_us"]["mean"] * 1e-6
    out["ops_budget"] = {"T2_echo_us": t2 * 1e6,
                         "gate_time_ns_ASSUMED": GATE_TIME_ASSUMED * 1e9,
                         "ratio": t2 / GATE_TIME_ASSUMED}
    return out


def estimator_checks(frozen):
    """Synthetic, noiseless checks of the FROZEN estimators on the exact
    HARDWARE sweep grids (the sim selftest never exercised these grids)."""
    chk = {}
    t = np.linspace(0, frozen.HW_T2_MAX, frozen.HW_T2_N)
    chk["t2_echo_bias_pct"] = {
        f"{T*1e6:.0f}us": (frozen.fit_exponential(t, 0.48 * np.exp(-t / T) + 0.505) / T - 1) * 100
        for T in (80e-6, 90e-6, 110e-6, 150e-6, 200e-6)}
    t = np.linspace(0, frozen.HW_T1_MAX, frozen.HW_T1_N)
    chk["t1_bias_pct"] = {
        f"{T*1e6:.0f}us": (frozen.fit_exponential(t, 0.97 * np.exp(-t / T) + 0.015) / T - 1) * 100
        for T in (80e-6, 110e-6, 125e-6, 200e-6)}
    d = np.linspace(0, frozen.HW_RAMSEY_MAX, frozen.HW_RAMSEY_N)
    chk["ramsey_reads_khz"] = {
        f"true {(250e3 + o)/1e3:.1f}kHz": frozen.fit_cos_frequency(
            d, 0.5 - 0.48 * np.exp(-d / 50e-6) * np.cos(2 * np.pi * (250e3 + o) * d)) / 1e3
        for o in (-22.8e3, +22.8e3, -5e3, +5e3)}
    x = np.linspace(0, 4 * np.pi, frozen.HW_RABI_N)
    chk["rabi_reads_rad"] = {
        f"true {2*np.pi/s:.3f}": 1 / frozen.fit_cos_frequency(x, np.sin(s * x / 2) ** 2)
        for s in (0.99, 1.00, 1.01)}
    return chk


def report(res, chk):
    f = lambda v, n=1: "—" if v is None else f"{v:.{n}f}"
    print("POST-HOC REANALYSIS (deviation; frozen script untouched)\n")
    for kind, label in (("t1", "T1"), ("t2", "T2 echo")):
        print(f"{label}: job | frozen fit | weighted NLLS ±1σ | floor B | red.χ²")
        for r in res[kind]["runs"]:
            flag = "" if r["single_exp_adequate"] else "  <- single exponential inadequate"
            print(f"  {r['job']} | {f(r['frozen_fit_us'])} us | "
                  f"{r['nlls_us']:.1f} ± {r['nlls_err_us']:.1f} us | "
                  f"{r['floor_B']:.3f} | {r['red_chi2']:.2f}{flag}")
        g, fg = res[kind]["nlls_group_us"], res[kind]["frozen_group_us"]
        print(f"  NLLS   mean {g['mean']:.1f} ± {g['sd']:.1f} us (sample SD, n={g['n']})")
        if fg:
            print(f"  frozen mean {fg['mean']:.1f} ± {fg['sd']:.1f} us (as published)")
        print()
    r = res["ramsey"]
    print(f"Ramsey: step {r['sample_step_us']:.1f} us -> Nyquist {r['nyquist_khz']:.1f} kHz "
          f"(programmed {r['programmed_khz']:.0f} kHz; at Nyquist: {r['at_nyquist']})")
    for b in r["alias_branches"]:
        print(f"  branch f = {b['f_khz']:.2f} ± {b['f_err_khz']:.2f} kHz, "
              f"T2* = {b['T2star_us']:.1f} ± {b['T2star_err_us']:.1f} us, RSS {b['rss']:.6f}")
    print(f"  aliases indistinguishable: {r['aliases_indistinguishable']}")
    print(f"  -> frame offset |δ| = {r['frame_offset_abs_khz']:.1f} ± "
          f"{r['frame_offset_err_khz']:.1f} kHz, sign undetermined "
          f"(frozen FFT read {f(r['frozen_fft_khz'], 2)} kHz)\n")
    r = res["rabi"]
    print(f"Rabi: NLLS period {r['nlls_period_rad']:.3f} ± {r['nlls_err_rad']:.3f} rad "
          f"(ideal {r['ideal_rad']:.3f}; frozen FFT {f(r['frozen_fft_rad'], 3)})\n")
    o = res["ops_budget"]
    print(f"Ops budget: T2 echo {o['T2_echo_us']:.1f} us / {o['gate_time_ns_ASSUMED']:.0f} ns "
          f"(ASSUMED gate time) = {o['ratio']:.2e}\n")
    if chk:
        print("Frozen-estimator checks on the HARDWARE grids (noiseless synthetic):")
        for k, v in chk.items():
            print(f"  {k}: " + ", ".join(f"{kk} -> {vv:+.1f}" if "pct" in k else
                                          f"{kk} -> {vv:.3f}" for kk, vv in v.items()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write full results to this JSON path")
    args = ap.parse_args()
    try:
        frozen = load_frozen()
    except ImportError as exc:   # qiskit missing: NLLS still runs
        print(f"[frozen script not importable ({exc}); frozen columns skipped]\n")
        frozen = None
    res = analyze(frozen)
    chk = estimator_checks(frozen) if frozen else None
    report(res, chk)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump({"results": res, "estimator_checks": chk}, fh, indent=2)
        print(f"\nJSON -> {args.json}")


if __name__ == "__main__":
    sys.exit(main())
