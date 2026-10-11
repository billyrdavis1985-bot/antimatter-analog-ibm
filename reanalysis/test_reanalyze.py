"""
Regression tests for reanalysis/reanalyze_posthoc.py.

Run from the repo root:  python -m pytest reanalysis/
Most tests need only numpy, scipy and pytest. Tests marked with the
`needs_frozen` skip reason also need qiskit + qiskit-aer (the README install).
"""

import importlib.util
import io
import json
import os
from contextlib import redirect_stdout

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("rp", os.path.join(HERE, "reanalyze_posthoc.py"))
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)

rng = np.random.default_rng(20261011)


def binomial(p, shots=rp.SHOTS):
    return rng.binomial(shots, np.clip(p, 0, 1)) / shots


def frozen_or_skip():
    try:
        return rp.load_frozen()
    except ImportError:
        pytest.skip("needs_frozen: qiskit/qiskit-aer not installed")


# ---- Estimators recover known values on the hardware grids ---------------

@pytest.mark.parametrize("T_true", [80e-6, 110e-6, 150e-6])
def test_decay_fit_recovers_T1(T_true):
    t = np.linspace(0, 400e-6, 21)
    y = binomial(0.97 * np.exp(-t / T_true) + 0.015)
    r = rp.fit_decay(t, y)
    assert abs(r["T_us"] - T_true * 1e6) < 4 * r["fit_sigma_us"]
    assert r["single_exp_adequate"]
    assert r["params_at_bound"] == []


@pytest.mark.parametrize("T_true", [80e-6, 90e-6, 110e-6])
def test_decay_fit_recovers_T2_echo_floor_half(T_true):
    # The regime where the frozen estimator reads +19% to +33% high.
    t = np.linspace(0, 400e-6, 21)
    y = binomial(0.48 * np.exp(-t / T_true) + 0.505)
    r = rp.fit_decay(t, y)
    assert abs(r["T_us"] / (T_true * 1e6) - 1) < 0.08


def test_rabi_fit_recovers_two_pi():
    x = np.linspace(0, 4 * np.pi, 21)
    r = rp.fit_rabi(x, binomial(np.sin(x / 2) ** 2))
    assert abs(r["period_rad"] - 2 * np.pi) < 4 * r["fit_sigma_rad"]


def test_ramsey_at_nyquist_gives_indistinguishable_aliases():
    d = np.linspace(0, 60e-6, 31)          # 2 us step: Nyquist = 250 kHz
    y = 0.5 - 0.45 * np.exp(-d / 40e-6) * np.cos(2 * np.pi * 227.5e3 * d)
    b = rp.fit_ramsey_branches(d, y, 250e3)
    assert np.isclose(b[0]["rss"], b[1]["rss"], rtol=1e-6)
    assert abs(b[0]["f_khz"] - 227.5) < 0.01 and abs(b[1]["f_khz"] - 272.5) < 0.01


def test_unweighted_fit_errors_not_double_inflated():
    # Regression: unweighted fits were inflated by sqrt(chi2) on top of
    # curve_fit's own residual scaling, so valid fits read as insignificant.
    d = np.linspace(0, 60e-6, 31)
    y = binomial(0.5 - 0.45 * np.exp(-d / 40e-6) * np.cos(2 * np.pi * 227.5e3 * d))
    w = rp.wfit(rp.ramsey_model, d, y, [-0.45, 227.5e3, 0, 40e-6, 0.5], rp.BOUNDS["ramsey"])
    u = rp.wfit(rp.ramsey_model, d, y, [-0.45, 227.5e3, 0, 40e-6, 0.5], rp.BOUNDS["ramsey"],
                weighted=False)
    assert u["err"][1] < 3 * w["err"][1]


def test_committed_ramsey_scan_has_no_failed_models():
    scan = rp.analyze(None)["ramsey"]["model_scan"]
    assert all("fit_failed" not in s for s in scan), scan


def test_ramsey_model_scan_agrees_on_clean_data():
    d = np.linspace(0, 60e-6, 31)
    y = binomial(0.5 - 0.45 * np.exp(-d / 40e-6) * np.cos(2 * np.pi * 227.5e3 * d))
    scan = rp.ramsey_model_scan(d, y, 227.5e3)
    fs = [s["f_khz"] for s in scan if "f_khz" in s]
    assert len(fs) == len(scan)
    assert max(fs) - min(fs) < 1.5     # well under the 2.4 kHz spread seen on hardware


# ---- Safeguards -----------------------------------------------------------

def test_flat_decay_is_rejected_not_fitted():
    # Regression: a flat line converged with a finite covariance and a
    # meaningless T (fit σ ~ 1e8 us). It must be rejected instead.
    t = np.linspace(0, 400e-6, 21)
    with pytest.raises(rp.FitError, match="not significant|not identifiable"):
        rp.fit_decay(t, np.full_like(t, 0.5))


def test_pure_noise_ramsey_is_rejected():
    d = np.linspace(0, 60e-6, 31)
    with pytest.raises(rp.FitError):
        rp.fit_ramsey_branches(d, binomial(np.full_like(d, 0.5)), 250e3)


@pytest.mark.parametrize("bad, msg", [
    ("0,0.5\n1,1.2\n2,0.3\n", "outside"),
    ("0,0.5\n2,0.4\n1,0.3\n", "increasing"),
    ("0,0.5\n1,nan\n2,0.3\n", "non-finite"),
])
def test_load_csv_rejects_bad_input(tmp_path, bad, msg):
    p = tmp_path / "fetch_x_t1.csv"
    p.write_text("# delay_s,P1\n" + bad)
    with pytest.raises(ValueError, match=msg):
        rp.load_csv(str(p))


def test_load_csv_checks_expected_length(tmp_path):
    p = tmp_path / "fetch_x_t1.csv"
    p.write_text("# delay_s,P1\n0,0.9\n1,0.5\n2,0.3\n")
    with pytest.raises(ValueError, match="expected 21"):
        rp.load_csv(str(p), expected_points=21)


# ---- End-to-end on the committed data -------------------------------------

def test_numpy_only_path_runs_and_reports():
    """Regression: without qiskit the report crashed on frozen columns."""
    res = rp.analyze(None)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rp.report(res, None)
    out = buf.getvalue()
    assert "frozen estimators unavailable" in out
    assert "apparent frame offset" in out


def test_committed_json_reproduces():
    frozen = frozen_or_skip()
    res = rp._jsonable({"results": rp.analyze(frozen),
                        "estimator_checks": rp.estimator_checks(frozen)})
    with open(os.path.join(HERE, "reanalysis-2026-10-11.json")) as fh:
        committed = json.load(fh)
    assert res == committed


def test_published_headline_values():
    """Pins the numbers quoted in README/ERRATA so a script change that moves
    them fails loudly instead of silently diverging from the docs."""
    r = rp.analyze(None)
    assert round(r["rabi"]["period_rad"], 3) == 6.284
    assert round(r["ramsey"]["offset_abs_khz_best_fit"], 1) == 22.5
    lo, hi = r["ramsey"]["offset_model_range_khz"]
    assert (round(lo, 1), round(hi, 1)) == (20.7, 23.1)
    if r["qubit_map_loaded"]:
        assert round(r["t2"]["per_qubit"]["70"]["weighted_us"]["mean"], 1) == 85.9
        assert round(r["t1"]["per_qubit"]["6"]["weighted_us"]["mean"], 1) == 108.5
