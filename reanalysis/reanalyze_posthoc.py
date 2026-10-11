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
Tests:
    ./.venv/bin/python -m pytest reanalysis/

Needs numpy + scipy. The side-by-side "frozen" column imports the frozen
estimators from the frozen script, which needs qiskit/qiskit-aer. Without them
the script still runs and reports the weighted fits only.

Uncertainty conventions (labelled everywhere in the output):
  fit σ      : 1-sigma statistical error from the fit covariance, inflated by
               sqrt(reduced χ²) when that exceeds 1. Covers shot noise only.
  sample SD  : standard deviation of a quantity across repeated runs.
  spread across tested models: how far a quantity moves across the specific fit
               models tried. A sensitivity check, NOT a full systematic
               uncertainty: models not tried could move it further.
"""

import argparse
import csv
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
GATE_TIME_ASSUMED = 60e-9    # the frozen script's assumption; used only without a qubit map
PROGRAMMED_DETUNING = 250e3  # Hz; equals DETUNING_SIM in the frozen script (checked when importable)

# Physical bounds (lower, upper) per model parameter. Fits that land on a
# bound are flagged, since the bound rather than the data then sets the value.
BOUNDS = {
    "expdec": ([0.0, 1e-6, -0.1], [1.5, 1e-2, 1.0]),                       # A, T, B
    "ramsey": ([-1.0, 1e3, -np.inf, 1e-7, 0.0], [1.0, 1e6, np.inf, 1e-2, 1.0]),  # A, f, phi, T2*, B
    "rabi": ([-1.0, 0.5, -np.inf, 0.0], [1.0, 50.0, np.inf, 1.0]),         # A, P, phi, B
}


class FitError(RuntimeError):
    """A fit that did not converge or whose parameters are not identifiable."""


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------
def load_frozen():
    spec = importlib.util.spec_from_file_location("frozen", FROZEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_csv(path, expected_points=None):
    """Load a fetch_*.csv and validate it: two columns, finite values,
    strictly increasing sweep, P1 within [0, 1], optional expected length."""
    d = np.atleast_2d(np.loadtxt(path, delimiter=","))
    name = os.path.basename(path)
    if d.shape[1] != 2:
        raise ValueError(f"{name}: expected 2 columns, got {d.shape[1]}")
    x, y = d[:, 0], d[:, 1]
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
        raise ValueError(f"{name}: non-finite values")
    if np.any(np.diff(x) <= 0):
        raise ValueError(f"{name}: sweep values are not strictly increasing")
    if np.any((y < 0) | (y > 1)):
        raise ValueError(f"{name}: P1 outside [0, 1]")
    if expected_points is not None and len(x) != expected_points:
        raise ValueError(f"{name}: {len(x)} points, expected {expected_points}")
    return x, y


def job_id(path):
    # fetch_<job_id>_<kind>.csv
    return os.path.basename(path)[len("fetch_"):].rsplit("_", 1)[0]


def load_qubit_map():
    """reanalysis/qubit-map.csv (from recover_qubits.py), keyed by job id.
    Returns {} if the map has not been generated yet."""
    path = os.path.join(REPO, "reanalysis", "qubit-map.csv")
    if not os.path.exists(path):
        return {}
    with open(path, newline="") as fh:
        return {r["job_id"]: r for r in csv.DictReader(fh)}


def _float_or_none(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def qubit_of(qmap, jid):
    q = qmap.get(jid, {}).get("physical_qubits", "")
    return q.strip("()").rstrip(",") or None


# --------------------------------------------------------------------------
# Models and fitting
# --------------------------------------------------------------------------
def expdec(t, A, T, B):
    return A * np.exp(-t / T) + B


def ramsey_model(t, A, f, phi, T2s, B):
    return A * np.exp(-t / T2s) * np.cos(2 * np.pi * f * t + phi) + B


def ramsey_gauss(t, A, f, phi, T2s, B):
    return A * np.exp(-(t / T2s) ** 2) * np.cos(2 * np.pi * f * t + phi) + B


def ramsey_drift(t, A, f, phi, T2s, B, C):
    return A * np.exp(-t / T2s) * np.cos(2 * np.pi * f * t + phi) + B + C * t


def rabi_model(x, A, P, phi, B):
    return A * np.cos(2 * np.pi * x / P + phi) + B


def binomial_sigma(p, shots=SHOTS):
    # Floor avoids zero weight at P1 = 0 or 1.
    return np.sqrt(np.clip(p * (1 - p), 1.0 / shots, None) / shots)


def wfit(model, x, y, p0, bounds=(-np.inf, np.inf), weighted=True):
    """Least-squares fit with safeguards. Returns a dict with params, fit σ
    (inflated by sqrt(reduced χ²) when it exceeds 1), reduced χ², RSS, and
    the indices of any parameters that ended on a bound.
    Raises FitError if the fit fails or the covariance is not finite."""
    sig = binomial_sigma(y)
    try:
        p, cov = curve_fit(model, x, y, p0=p0, sigma=sig if weighted else None,
                           absolute_sigma=weighted, bounds=bounds, maxfev=50000)
    except (RuntimeError, ValueError) as exc:
        raise FitError(f"{model.__name__}: did not converge ({exc})") from exc
    if not np.all(np.isfinite(cov)):
        raise FitError(f"{model.__name__}: covariance not finite (parameters not identifiable)")
    resid = y - model(x, *p)
    dof = len(x) - len(p)
    if dof <= 0:
        raise FitError(f"{model.__name__}: {len(x)} points for {len(p)} parameters")
    chi2r = float(np.sum((resid / sig) ** 2) / dof)
    # Weighted fits: inflate by sqrt(red. chi2) when the model underfits. Unweighted
    # fits: curve_fit already scales the covariance to the residual scatter, so a
    # second inflation would double-count.
    err = np.sqrt(np.diag(cov)) * (np.sqrt(max(chi2r, 1.0)) if weighted else 1.0)
    lo, hi = np.broadcast_to(bounds[0], p.shape), np.broadcast_to(bounds[1], p.shape)
    span = np.where(np.isfinite(hi - lo), hi - lo, 1.0)
    at_bound = [i for i in range(len(p))
                if abs(p[i] - lo[i]) < 1e-6 * span[i] or abs(hi[i] - p[i]) < 1e-6 * span[i]]
    return {"p": p, "err": err, "chi2r": chi2r, "rss": float(np.sum(resid ** 2)),
            "at_bound": at_bound,
            "prediction_in_unit_interval": prediction_in_unit_interval(model, p, x)}


def prediction_in_unit_interval(model, p, x, tol=1e-3):
    """A fitted probability curve must stay within [0, 1] over the swept range.
    Parameter bounds alone do not guarantee this (e.g. A + B > 1)."""
    xx = np.linspace(np.min(x), np.max(x), 2001)
    f = model(xx, *p)
    return bool(np.all(f >= -tol) and np.all(f <= 1 + tol))


def require_identifiable(r, amp_idx, key_idx, what):
    """A fit can converge with a finite covariance and still be meaningless:
    if the signal amplitude is not significant, the time constant or frequency
    is set by nothing. Reject both cases explicitly."""
    A, sA = abs(r["p"][amp_idx]), r["err"][amp_idx]
    K, sK = abs(r["p"][key_idx]), r["err"][key_idx]
    if A < 3 * sA:
        raise FitError(f"{what}: signal amplitude not significant ({A:.3g} ± {sA:.2g})")
    if sK > 0.5 * K:
        raise FitError(f"{what}: parameter not identifiable (relative fit σ {sK / K:.0%})")


def fit_decay(t, y):
    """T1 or T2-echo decay: A·exp(-t/T) + B."""
    r = wfit(expdec, t, y, [max(y[0] - y[-1], 0.05), 100e-6, y[-1]], BOUNDS["expdec"])
    require_identifiable(r, 0, 1, "decay fit")
    A, T, B = r["p"]
    return {"T_us": T * 1e6, "fit_sigma_us": r["err"][1] * 1e6, "floor_B": B,
            "red_chi2": r["chi2r"], "single_exp_adequate": r["chi2r"] <= CHI2_FLAG,
            "params_at_bound": r["at_bound"],
            "prediction_in_unit_interval": r["prediction_in_unit_interval"]}


def fit_ramsey_branches(d, y, programmed):
    """Fit starting on each side of `programmed`. If the sweep samples at the
    Nyquist limit, both branches reach identical residuals (an alias pair)."""
    out = []
    for f0 in (programmed - 25e3, programmed + 25e3):
        r = wfit(ramsey_model, d, y, [-0.45, f0, 0.0, 40e-6, 0.5], BOUNDS["ramsey"])
        require_identifiable(r, 0, 1, "Ramsey fit")
        out.append({"f_khz": r["p"][1] / 1e3, "fit_sigma_khz": r["err"][1] / 1e3,
                    "T2star_us": r["p"][3] * 1e6, "T2star_fit_sigma_us": r["err"][3] * 1e6,
                    "red_chi2": r["chi2r"], "rss": r["rss"],
                    "params_at_bound": r["at_bound"],
                    "prediction_in_unit_interval": r["prediction_in_unit_interval"]})
    return out


def ramsey_model_scan(d, y, f0):
    """Refit the Ramsey fringe frequency under several reasonable models. The
    spread is a sensitivity check across THESE models, not a complete
    systematic uncertainty."""
    h = len(d) // 2 + 1
    b5 = BOUNDS["ramsey"]
    b6 = (b5[0] + [-np.inf], b5[1] + [np.inf])
    specs = [
        ("exponential envelope, weighted", ramsey_model, d, y, [-0.45, f0, 0, 40e-6, 0.5], b5, True),
        ("exponential envelope, unweighted", ramsey_model, d, y, [-0.45, f0, 0, 40e-6, 0.5], b5, False),
        ("Gaussian envelope", ramsey_gauss, d, y, [-0.45, f0, 0, 40e-6, 0.5], b5, True),
        ("exponential + linear baseline drift", ramsey_drift, d, y, [-0.45, f0, 0, 40e-6, 0.5, 0], b6, True),
        ("first half of sweep only", ramsey_model, d[:h], y[:h], [-0.45, f0, 0, 40e-6, 0.5], b5, True),
        ("second half of sweep only", ramsey_model, d[h - 1:], y[h - 1:], [-0.3, f0, 0, 40e-6, 0.5], b5, True),
    ]
    rows = []
    for name, model, x, yy, p0, bnds, w in specs:
        try:
            r = wfit(model, x, yy, p0, bnds, weighted=w)
            require_identifiable(r, 0, 1, name)
            rows.append({"model": name, "f_khz": r["p"][1] / 1e3,
                         "fit_sigma_khz": r["err"][1] / 1e3, "red_chi2": r["chi2r"]})
        except FitError as exc:
            rows.append({"model": name, "fit_failed": str(exc)})
    return rows


def fit_rabi(x, y):
    r = wfit(rabi_model, x, y, [-0.5, 2 * np.pi, 0.0, 0.5], BOUNDS["rabi"])
    require_identifiable(r, 0, 1, "Rabi fit")
    return {"period_rad": r["p"][1], "fit_sigma_rad": r["err"][1], "red_chi2": r["chi2r"],
            "params_at_bound": r["at_bound"],
            "prediction_in_unit_interval": r["prediction_in_unit_interval"]}


def sampling_check(d, programmed):
    """Nyquist analysis is only meaningful for a uniformly spaced sweep."""
    steps = np.diff(d)
    uniform = bool(np.allclose(steps, steps[0], rtol=1e-6, atol=0))
    if not uniform:
        return {"uniform_spacing": False, "sample_step_us": None, "nyquist_khz": None,
                "at_nyquist": None}
    nyq = 1 / (2 * steps[0])
    return {"uniform_spacing": True, "sample_step_us": steps[0] * 1e6,
            "nyquist_khz": nyq / 1e3, "at_nyquist": bool(np.isclose(nyq, programmed))}


def group(vals):
    """Mean and sample SD across runs (SD is None for a single run)."""
    v = np.asarray(vals, dtype=float)
    return {"mean": float(v.mean()),
            "sample_sd": float(v.std(ddof=1)) if len(v) > 1 else None,
            "n": int(len(v))}


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------
def analyze(frozen, qmap=None):
    """frozen: the imported frozen script, or None (weighted fits only).
    qmap: {job_id: row} from qubit-map.csv; loaded from disk when None. Jobs
    missing from the map are grouped as "unmapped" rather than failing."""
    if frozen is not None and frozen.DETUNING_SIM != PROGRAMMED_DETUNING:
        raise ValueError("PROGRAMMED_DETUNING no longer matches the frozen script")
    n_pts = ({"t1": frozen.HW_T1_N, "t2": frozen.HW_T2_N, "ramsey": frozen.HW_RAMSEY_N,
              "rabi": frozen.HW_RABI_N} if frozen else {})
    out = {"deviation": "post-hoc reanalysis, not preregistered", "shots": SHOTS,
           "frozen_estimators_available": frozen is not None,
           "uncertainty_conventions": {
               "fit_sigma": "1-sigma from fit covariance, inflated by sqrt(red. chi2) if >1",
               "sample_sd": "standard deviation across repeated runs",
               "spread_across_tested_models": "sensitivity across the fit models tried; "
                                              "not a complete systematic uncertainty"}}
    if qmap is None:
        qmap = load_qubit_map()
    out["qubit_map_loaded"] = bool(qmap)

    # ---- T1 and T2 echo -------------------------------------------------
    for kind in ("t1", "t2"):
        rows = []
        for path in sorted(glob.glob(os.path.join(REPO, f"fetch_*_{kind}.csv"))):
            t, y = load_csv(path, n_pts.get(kind))
            jid = job_id(path)
            row = {"job": jid, "qubit": qubit_of(qmap, jid),
                   "frozen_fit_us": frozen.fit_exponential(t, y) * 1e6 if frozen else None}
            try:
                row.update(fit_decay(t, y))
            except FitError as exc:
                row["fit_failed"] = str(exc)
            rows.append(row)
        ok = [r for r in rows if "fit_failed" not in r]
        out[kind] = {"runs": rows,
                     "pooled_all_qubits": {
                         "weighted_us": group([r["T_us"] for r in ok]),
                         "frozen_us": group([r["frozen_fit_us"] for r in rows]) if frozen else None,
                         "warning": "pools different physical qubits; not a physical quantity"
                                    if qmap else "qubit map not loaded"}}
        if qmap:
            per_q = {}
            for r in ok:
                per_q.setdefault(r["qubit"] or "unmapped", []).append(r)
            col = "ibm_T1_us" if kind == "t1" else "ibm_T2_us"
            out[kind]["per_qubit"] = {
                q: {"weighted_us": group([r["T_us"] for r in rs]),
                    "fit_sigma_us_per_run": [r["fit_sigma_us"] for r in rs],
                    "frozen_us": group([r["frozen_fit_us"] for r in rs]) if frozen else None,
                    "ibm_reported_us": _float_or_none(qmap.get(rs[0]["job"], {}).get(col)),
                    "jobs": [r["job"] for r in rs]}
                for q, rs in per_q.items()}
            unmapped = [r["job"] for r in rows if r["qubit"] is None]
            if unmapped:
                out[kind]["unmapped_jobs"] = unmapped

    # ---- Ramsey -----------------------------------------------------------
    path = glob.glob(os.path.join(REPO, "fetch_*_ramsey.csv"))[0]
    d, y = load_csv(path, n_pts.get("ramsey"))
    prog = PROGRAMMED_DETUNING
    samp = sampling_check(d, prog)
    branches = fit_ramsey_branches(d, y, prog)
    scan = ramsey_model_scan(d, y, branches[0]["f_khz"] * 1e3)
    offs = [abs(s["f_khz"] - prog / 1e3) for s in scan if "f_khz" in s]
    best = branches[0]
    out["ramsey"] = {
        "job": job_id(path), "qubit": qubit_of(qmap, job_id(path)),
        "programmed_khz": prog / 1e3, **samp,
        "frozen_fft_khz": frozen.fit_cos_frequency(d, y) / 1e3 if frozen else None,
        "alias_branches": branches,
        "aliases_indistinguishable": bool(np.isclose(branches[0]["rss"],
                                                     branches[1]["rss"], rtol=1e-6)),
        "offset_abs_khz_best_fit": abs(best["f_khz"] - prog / 1e3),
        "offset_fit_sigma_khz": best["fit_sigma_khz"],
        "single_tone_adequate": best["red_chi2"] <= CHI2_FLAG,
        "model_scan": scan,
        "offset_spread_across_tested_models_khz": [min(offs), max(offs)] if offs else None,
    }

    # ---- Rabi ---------------------------------------------------------------
    path = glob.glob(os.path.join(REPO, "fetch_*_rabi.csv"))[0]
    x, y = load_csv(path, n_pts.get("rabi"))
    out["rabi"] = {"job": job_id(path),
                   "frozen_fft_rad": 1 / frozen.fit_cos_frequency(x, y) if frozen else None,
                   **fit_rabi(x, y), "ideal_rad": 2 * np.pi,
                   "note": "Rx(theta) compiles to virtual-Z around fixed sqrt(X) "
                           "pulses: a gate-phase sweep, not a drive-amplitude Rabi."}

    # ---- Coherent-ops budget (transmon side only) -------------------------
    if qmap and "per_qubit" in out["t2"]:
        out["ops_budget"] = {}
        for q, g in out["t2"]["per_qubit"].items():
            sx_ns = _float_or_none(qmap.get(g["jobs"][0], {}).get("sx_ns"))
            if q == "unmapped" or sx_ns is None:
                continue
            t2q = g["weighted_us"]["mean"] * 1e-6
            out["ops_budget"][q] = {"T2_echo_us": t2q * 1e6, "sx_ns_ibm_reported": sx_ns,
                                    "ratio": t2q / (sx_ns * 1e-9)}
    else:
        t2 = out["t2"]["pooled_all_qubits"]["weighted_us"]["mean"] * 1e-6
        out["ops_budget"] = {"pooled": {"T2_echo_us": t2 * 1e6,
                                        "gate_time_ns_ASSUMED": GATE_TIME_ASSUMED * 1e9,
                                        "ratio": t2 / GATE_TIME_ASSUMED}}
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


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
def _num(v, n=1):
    return "—" if v is None else f"{v:.{n}f}"


def _grp(g, unit="us"):
    """'mean ± SD (sample SD, n=k)', or 'value (n=1)'. None-safe."""
    if g is None:
        return "—"
    if g["sample_sd"] is None:
        return f"{g['mean']:.1f} {unit} (n=1)"
    return f"{g['mean']:.1f} ± {g['sample_sd']:.1f} {unit} (sample SD, n={g['n']})"


def report(res, chk):
    print("POST-HOC REANALYSIS (deviation; frozen script untouched)")
    if not res["frozen_estimators_available"]:
        print("[frozen estimators unavailable (qiskit not installed): frozen columns show —]")
    print("± conventions: fit σ = statistical, from the fit; sample SD = across runs;"
          " spread = across the fit models tried (a sensitivity check, not a full systematic)\n")
    for kind, label in (("t1", "T1"), ("t2", "T2 echo")):
        print(f"{label}: job | qubit | frozen fit | weighted fit ± fit σ | floor B | red.χ²")
        for r in res[kind]["runs"]:
            if "fit_failed" in r:
                print(f"  {r['job']} | q{r['qubit'] or '?'} | FIT FAILED: {r['fit_failed']}")
                continue
            flags = []
            if not r["single_exp_adequate"]:
                flags.append("single exponential inadequate")
            if r["params_at_bound"]:
                flags.append(f"params {r['params_at_bound']} at bound")
            if not r["prediction_in_unit_interval"]:
                flags.append("fitted curve leaves [0, 1]")
            flag = f"  <- {'; '.join(flags)}" if flags else ""
            print(f"  {r['job']} | q{r['qubit'] or '?'} | {_num(r['frozen_fit_us'])} us | "
                  f"{r['T_us']:.1f} ± {r['fit_sigma_us']:.1f} us | "
                  f"{r['floor_B']:.3f} | {r['red_chi2']:.2f}{flag}")
        pooled = res[kind]["pooled_all_qubits"]
        print(f"  pooled, weighted: {_grp(pooled['weighted_us'])}  [{pooled['warning']}]")
        if pooled["frozen_us"]:
            print(f"  pooled, frozen (as published): {_grp(pooled['frozen_us'])}")
        if "per_qubit" in res[kind]:
            print("  per qubit:")
            for q, g in res[kind]["per_qubit"].items():
                sig = ", ".join(f"{s:.1f}" for s in g["fit_sigma_us_per_run"])
                ibm = _num(g["ibm_reported_us"])
                print(f"    q{q}: weighted {_grp(g['weighted_us'])}; fit σ per run [{sig}] us | "
                      f"frozen {_grp(g['frozen_us'])} | IBM-reported {ibm} us")
            if res[kind].get("unmapped_jobs"):
                print(f"  WARNING: jobs missing from qubit map: {res[kind]['unmapped_jobs']}")
        print()

    r = res["ramsey"]
    if r["uniform_spacing"]:
        print(f"Ramsey (q{r['qubit'] or '?'}): step {r['sample_step_us']:.1f} us -> Nyquist "
              f"{r['nyquist_khz']:.1f} kHz (programmed {r['programmed_khz']:.0f} kHz; "
              f"at Nyquist: {r['at_nyquist']})")
    else:
        print(f"Ramsey (q{r['qubit'] or '?'}): NON-UNIFORM sampling; Nyquist analysis not applicable")
    for b in r["alias_branches"]:
        print(f"  branch f = {b['f_khz']:.2f} ± {b['fit_sigma_khz']:.2f} kHz (fit σ), "
              f"T2* = {b['T2star_us']:.1f} ± {b['T2star_fit_sigma_us']:.1f} us, "
              f"red.χ² {b['red_chi2']:.1f}, RSS {b['rss']:.6f}")
    print(f"  aliases indistinguishable: {r['aliases_indistinguishable']}")
    print("  model scan (sensitivity across the models tried):")
    for s in r["model_scan"]:
        if "fit_failed" in s:
            print(f"    {s['model']:38s} FIT FAILED: {s['fit_failed']}")
        else:
            print(f"    {s['model']:38s} |δ| = {abs(s['f_khz'] - r['programmed_khz']):5.2f} kHz"
                  f"  red.χ² {s['red_chi2']:6.1f}")
    lo, hi = r["offset_spread_across_tested_models_khz"]
    adequacy = "" if r["single_tone_adequate"] else \
        f" Single-tone model fits poorly (red.χ² {r['alias_branches'][0]['red_chi2']:.0f})."
    print(f"  -> apparent frame offset |δ| ≈ {r['offset_abs_khz_best_fit']:.1f} kHz "
          f"(fit σ ±{r['offset_fit_sigma_khz']:.1f}; spread across tested models {lo:.1f}–{hi:.1f} kHz); "
          f"sign undetermined.{adequacy}")
    print(f"     frozen FFT read {_num(r['frozen_fft_khz'], 2)} kHz\n")

    r = res["rabi"]
    print(f"Rabi: period {r['period_rad']:.3f} ± {r['fit_sigma_rad']:.3f} rad (fit σ), "
          f"red.χ² {r['red_chi2']:.1f} (ideal {r['ideal_rad']:.3f}; "
          f"frozen FFT {_num(r['frozen_fft_rad'], 3)})\n")

    for q, o in res["ops_budget"].items():
        gate = (f"{o['sx_ns_ibm_reported']:.0f} ns (IBM-reported sx)" if "sx_ns_ibm_reported" in o
                else f"{o['gate_time_ns_ASSUMED']:.0f} ns (ASSUMED)")
        print(f"Ops budget [{'q' + q if q != 'pooled' else q}]: T2 echo "
              f"{o['T2_echo_us']:.1f} us / {gate} = {o['ratio']:.2e}")
    print()
    if chk:
        print("Frozen-estimator checks on the HARDWARE grids (noiseless synthetic):")
        for k, v in chk.items():
            print(f"  {k}: " + ", ".join(f"{kk} -> {vv:+.1f}" if "pct" in k else
                                          f"{kk} -> {vv:.3f}" for kk, vv in v.items()))


def _jsonable(o):
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write full results to this JSON path")
    args = ap.parse_args()
    try:
        frozen = load_frozen()
    except ImportError:          # qiskit missing: weighted fits still run
        frozen = None
    res = analyze(frozen)
    chk = estimator_checks(frozen) if frozen else None
    report(res, chk)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(_jsonable({"results": res, "estimator_checks": chk}), fh, indent=2)
        print(f"\nJSON -> {args.json}")


if __name__ == "__main__":
    sys.exit(main())
