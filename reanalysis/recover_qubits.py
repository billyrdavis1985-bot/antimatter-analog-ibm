#!/usr/bin/env python3
"""
recover_qubits.py — recover which PHYSICAL qubit each ibm_fez job ran on, and
IBM's own reported T1 / T2 / sx duration / readout error for that qubit at
(or just before) job creation time.

Why: the frozen script never recorded the transpiler's qubit choice, so two
README claims are currently unverified:
  (a) "T1 rep 1 is an outlier because the transpiler picked a different qubit"
  (b) "the Ramsey deviation is linked to the below-average T1 qubit"
This settles both, and gives an independent per-qubit reference (IBM's
calibration) to compare the measured T1/T2 against.

Decision it changes: if all T1 reps ran on the same qubit, claim (a) is
retracted and rep 1 is real drift; if Ramsey ran on a different qubit than
T1 rep 1, claim (b) is retracted.

Read-only: queries job records and calibration data. Uses NO QPU time.

Usage (README venv, saved IBM account):
    ./.venv/bin/python -I reanalysis/recover_qubits.py            # all jobs in repo
    ./.venv/bin/python -I reanalysis/recover_qubits.py <job_id> ...
Writes reanalysis/qubit-map.csv. Commit that file as-is.
"""

import csv
import glob
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "reanalysis", "qubit-map.csv")


def repo_jobs():
    jobs = []
    for p in sorted(glob.glob(os.path.join(REPO, "fetch_*.csv"))):
        jid, kind = os.path.basename(p)[len("fetch_"):-len(".csv")].rsplit("_", 1)
        jobs.append((jid, kind))
    return jobs


def pub_circuit(pub):
    """A decoded pub is a QuantumCircuit, a (circuit, ...) tuple, or a SamplerPub."""
    if hasattr(pub, "circuit"):
        return pub.circuit
    if isinstance(pub, (list, tuple)):
        return pub[0]
    return pub


def measured_qubits(circuit):
    """Physical qubit indices that carry a measurement in a transpiled circuit."""
    return sorted({circuit.find_bit(q).index
                   for inst in circuit.data if inst.operation.name == "measure"
                   for q in inst.qubits})


def job_qubits(job):
    pubs = job.inputs.get("pubs", [])
    per_circuit = [tuple(measured_qubits(pub_circuit(p))) for p in pubs]
    distinct = sorted(set(per_circuit))
    return per_circuit, distinct


def calibration(backend, qubit, when):
    """IBM-reported properties for `qubit` at the snapshot just before `when`.
    Falls back to CURRENT properties (flagged) if historical lookup fails."""
    source = "at_job_time"
    try:
        props = backend.properties(datetime=when)
    except Exception as exc:          # NotImplementedError on some channels
        print(f"  historical properties unavailable ({type(exc).__name__}); using CURRENT")
        props, source = backend.properties(refresh=True), "CURRENT_not_job_time"
    if props is None:
        return {"cal_source": "none"}

    def safe(fn, *a):
        try:
            return fn(*a)
        except Exception:
            return None

    t1, t2 = safe(props.t1, qubit), safe(props.t2, qubit)
    sx = safe(props.gate_length, "sx", qubit)
    ro = safe(props.readout_error, qubit)
    return {"cal_source": source,
            "cal_timestamp": str(getattr(props, "last_update_date", "")),
            "ibm_T1_us": None if t1 is None else round(t1 * 1e6, 1),
            "ibm_T2_us": None if t2 is None else round(t2 * 1e6, 1),
            "sx_ns": None if sx is None else round(sx * 1e9, 1),
            "readout_err": ro}


def main():
    from qiskit_ibm_runtime import QiskitRuntimeService
    service = QiskitRuntimeService()
    wanted = [(j, "?") for j in sys.argv[1:]] or repo_jobs()
    rows, backends = [], {}
    for jid, kind in wanted:
        job = service.job(jid)
        bname = job.backend().name
        backend = backends.setdefault(bname, service.backend(bname))
        created = job.creation_date
        per_circuit, distinct = job_qubits(job)
        print(f"{jid} [{kind}] {bname} created {created}: qubits {distinct}"
              + ("  <-- MORE THAN ONE LAYOUT IN THIS JOB" if len(distinct) > 1 else ""))
        q = distinct[0][0] if len(distinct) == 1 and len(distinct[0]) == 1 else None
        row = {"job_id": jid, "experiment": kind, "backend": bname,
               "created": str(created), "physical_qubits": ";".join(map(str, distinct)),
               "n_circuits": len(per_circuit)}
        if q is not None:
            row.update(calibration(backend, q, created))
        rows.append(row)

    keys = sorted({k for r in rows for k in r}, key=lambda k: (k not in rows[0], k))
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
