"""
Synthetic portfolio data generator.

Builds a realistic, fully fictional 8-project digital transformation programme
for "Northwind Utilities" and writes it to /data as CSV files.

The data is random but *seeded*, so every run produces identical files.
A handful of real-world PMO problems are planted on purpose, so the dashboard
has something to find:

  * two projects drifting over budget / behind schedule (Red RAG)
  * a phase-2 SOW still awaiting signature while work has already started
  * an SOW that expired with no extension raised
  * a month where two consultants were left off the client invoice
  * a few people booked well over 100% capacity
  * risk actions that have slipped past their due date

Run:  python -m pmo.generate_data
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Reporting window: Jan-Sep 2026, month-end snapshots.
MONTHS = pd.period_range("2026-01", "2026-09", freq="M")
CAPACITY_DAYS = 20  # billable days per person per month

# ---------------------------------------------------------------------------
# Projects. cpi/spi = where performance ends up by September (1.0 = on plan).
# ---------------------------------------------------------------------------
PROJECTS = [
    # id,  name,                            workstream,       pm,               start,     end,       budget,    cpi,  spi
    ("P01", "ERP Finance Migration",         "Finance",        "Priya Raman",    "2025-11", "2026-12", 2_400_000, 0.98, 1.01),
    ("P02", "Customer Portal Rebuild",       "Digital",        "Tom Hughes",     "2026-01", "2026-11", 1_350_000, 0.91, 0.93),
    ("P03", "Data Warehouse Modernisation",  "Data",           "Aisha Okafor",   "2025-10", "2026-12", 3_100_000, 0.80, 0.83),
    ("P04", "Field Workforce Mobile App",    "Digital",        "Tom Hughes",     "2026-02", "2026-12",   880_000, 1.03, 0.97),
    ("P05", "Smart Meter Data Platform",     "Data",           "Aisha Okafor",   "2026-01", "2027-03", 2_750_000, 0.94, 0.88),
    ("P06", "Cyber Security Uplift",         "Infrastructure", "Daniel Clarke",  "2026-01", "2026-10",   960_000, 1.01, 1.04),
    ("P07", "Cloud Hosting Migration",       "Infrastructure", "Daniel Clarke",  "2025-12", "2026-11", 1_900_000, 0.82, 0.96),
    ("P08", "HR & Payroll Integration",      "Corporate",      "Sophie Bennett", "2026-03", "2027-01",   720_000, 0.97, 0.93),
]

ROLES = {  # role: (day rate GBP, headcount)
    "Project Manager": (750, 4),
    "Business Analyst": (600, 7),
    "Solution Architect": (900, 4),
    "Developer": (550, 12),
    "Data Engineer": (650, 6),
    "Test Analyst": (480, 6),
    "PMO Analyst": (420, 3),
}

FIRST = ["Oliver", "Amelia", "Arjun", "Isla", "Noah", "Mia", "Leo", "Zara", "Ethan", "Grace",
         "Ravi", "Chloe", "Lucas", "Hannah", "Kwame", "Ella", "Jack", "Freya", "Omar", "Ruby",
         "Sam", "Lily", "Harry", "Anya", "Ben", "Maya", "Finn", "Nia", "Owen", "Ivy",
         "Rohan", "Evie", "Max", "Leah", "Adam", "Tara", "Kai", "Erin", "Theo", "Sara",
         "Dev", "Holly"]
LAST = ["Patel", "Smith", "Jones", "Khan", "Taylor", "Brown", "Wilson", "Evans", "Thomas", "Roberts",
        "Walker", "Wright", "Green", "Hall", "Wood", "Shah", "Murphy", "Hughes", "Edwards", "Lewis",
        "Ali", "Turner", "Baker", "Hill", "Cooper", "Ward", "Morris", "King", "Price", "Bell",
        "Iyer", "Fox", "Reid", "Gray", "Mills", "Rose", "Lowe", "Dean", "Nash", "Webb",
        "Bose", "Hart"]

RISK_LIBRARY = [
    ("Key SME availability limited during UAT", "Resource"),
    ("Legacy data quality worse than assumed", "Data"),
    ("Third-party API delivery delayed", "Supplier"),
    ("Scope creep from business change requests", "Scope"),
    ("Integration environment unstable", "Technical"),
    ("Regulatory sign-off later than planned", "Compliance"),
    ("Licence costs exceed estimate", "Financial"),
    ("Critical-path developer attrition", "Resource"),
    ("Cut-over window clashes with peak billing period", "Schedule"),
    ("Security penetration test findings require rework", "Technical"),
    ("Business readiness / training not started", "Change"),
    ("Vendor rate card increase at renewal", "Financial"),
]
RISK_OWNERS = ["Priya Raman", "Tom Hughes", "Aisha Okafor", "Daniel Clarke", "Sophie Bennett"]


def s_curve(t: np.ndarray) -> np.ndarray:
    """Cumulative share of work planned by fraction-of-duration t (0..1).
    Projects spend slowly, ramp up, then taper: the classic S-curve."""
    t = np.clip(t, 0, 1)
    return 3 * t**2 - 2 * t**3


def month_index(period: pd.Period) -> int:
    return period.year * 12 + period.month


def build_projects() -> pd.DataFrame:
    df = pd.DataFrame(PROJECTS, columns=["project_id", "project_name", "workstream", "project_manager",
                                         "start_month", "end_month", "budget_gbp", "target_cpi", "target_spi"])
    return df


def build_evm(projects: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Monthly cumulative Planned Value, Earned Value and Actual Cost."""
    rows = []
    for p in projects.itertuples():
        start, end = pd.Period(p.start_month, "M"), pd.Period(p.end_month, "M")
        duration = month_index(end) - month_index(start) + 1
        ev_prev = ac_prev = 0.0
        for i, m in enumerate(MONTHS):
            elapsed = month_index(m) - month_index(start) + 1
            if elapsed <= 0:
                continue
            pv = p.budget_gbp * s_curve(np.array(elapsed / duration))
            # Performance drifts from on-plan (1.0) toward its September value.
            progress = (i + 1) / len(MONTHS)
            spi = 1 + (p.target_spi - 1) * progress + rng.normal(0, 0.012)
            cpi = 1 + (p.target_cpi - 1) * progress + rng.normal(0, 0.012)
            ev = max(ev_prev, min(pv * spi, p.budget_gbp))
            ac = max(ac_prev, ev / cpi)
            ev_prev, ac_prev = ev, ac
            rows.append({"project_id": p.project_id, "month": str(m),
                         "planned_value": round(float(pv)), "earned_value": round(ev), "actual_cost": round(ac)})
    return pd.DataFrame(rows)


def build_resources(rng: np.random.Generator) -> pd.DataFrame:
    rows, n = [], 0
    names = rng.permutation([f"{f} {l}" for f, l in zip(FIRST, rng.permutation(LAST))])
    for role, (rate, count) in ROLES.items():
        for _ in range(count):
            n += 1
            rows.append({"resource_id": f"R{n:03d}", "name": names[n - 1], "role": role,
                         "day_rate_gbp": rate, "capacity_days": CAPACITY_DAYS})
    return pd.DataFrame(rows)


def build_allocations(projects, resources, rng) -> pd.DataFrame:
    """Who is booked to which project, how many days, each month."""
    proj_ids = projects.project_id.tolist()
    home = {r: rng.choice(proj_ids) for r in resources.resource_id}
    # PMs and PMO analysts mostly stay put; others sometimes split across two projects.
    rows = []
    overloaded = set(rng.choice(resources.resource_id, 4, replace=False))
    bench = set(rng.choice(list(set(resources.resource_id) - overloaded), 3, replace=False))
    starts = projects.set_index("project_id").start_month.map(lambda x: pd.Period(x, "M"))
    for r in resources.itertuples():
        second = rng.choice([p for p in proj_ids if p != home[r.resource_id]])
        for i, m in enumerate(MONTHS):
            if starts[home[r.resource_id]] > m:
                continue
            second_live = starts[second] <= m
            base = int(rng.integers(14, 18))
            if r.resource_id in overloaded and i >= 4 and second_live:
                base = int(rng.integers(19, 22))
                rows.append({"resource_id": r.resource_id, "project_id": second, "month": str(m),
                             "allocated_days": int(rng.integers(5, 9))})
            elif r.resource_id in bench and i >= 5:
                base = int(rng.integers(5, 10))
            elif rng.random() < 0.25 and second_live:
                rows.append({"resource_id": r.resource_id, "project_id": second, "month": str(m),
                             "allocated_days": int(rng.integers(2, 5))})
            rows.append({"resource_id": r.resource_id, "project_id": home[r.resource_id], "month": str(m),
                         "allocated_days": base})
    return pd.DataFrame(rows)


def build_timesheets(allocations, rng) -> pd.DataFrame:
    ts = allocations.copy()
    noise = rng.integers(-1, 2, len(ts))
    ts["days_logged"] = (ts.allocated_days + noise).clip(lower=0)
    return ts[["resource_id", "project_id", "month", "days_logged"]]


def build_sows(projects) -> pd.DataFrame:
    rows = []
    for p in projects.itertuples():
        s = pd.Period(p.start_month, "M")
        mid = pd.Period("2026-06", "M")
        if p.project_id == "P05":
            # Phase 2 started in July but the SOW is still with the client for signature.
            rows += [(f"SOW-{p.project_id}-1", p.project_id, str(s), "2026-06", round(p.budget_gbp * 0.45), "Signed"),
                     (f"SOW-{p.project_id}-2", p.project_id, "2026-07", p.end_month, round(p.budget_gbp * 0.55), "Pending signature")]
        elif p.project_id == "P07":
            # Only SOW ran to end of June; extension never raised, but the team kept working.
            rows += [(f"SOW-{p.project_id}-1", p.project_id, str(s), "2026-06", round(p.budget_gbp * 0.6), "Signed")]
        elif s <= mid:
            rows += [(f"SOW-{p.project_id}-1", p.project_id, str(s), "2026-06", round(p.budget_gbp * 0.5), "Signed"),
                     (f"SOW-{p.project_id}-2", p.project_id, "2026-07", p.end_month, round(p.budget_gbp * 0.5), "Signed")]
        else:
            rows += [(f"SOW-{p.project_id}-1", p.project_id, str(s), p.end_month, p.budget_gbp, "Signed")]
    return pd.DataFrame(rows, columns=["sow_id", "project_id", "start_month", "end_month", "value_gbp", "status"])


def build_invoices(timesheets, resources, sows, rng) -> pd.DataFrame:
    """What was actually billed to the client per project per month."""
    rates = resources.set_index("resource_id").day_rate_gbp
    ts = timesheets.assign(value=timesheets.days_logged * timesheets.resource_id.map(rates))
    rows = []
    for (pid, month), g in ts.groupby(["project_id", "month"]):
        m = pd.Period(month, "M")
        covered = sows[(sows.project_id == pid) & (sows.status == "Signed")]
        covered = covered[(covered.start_month.map(lambda x: pd.Period(x, "M")) <= m) &
                          (covered.end_month.map(lambda x: pd.Period(x, "M")) >= m)]
        if covered.empty:
            continue  # cannot invoice without a signed SOW: revenue silently stuck
        days, value = g.days_logged.sum(), g.value.sum()
        if pid == "P02" and month == "2026-08":
            # Two consultants left off the invoice.
            dropped = g.nlargest(2, "value")
            days -= dropped.days_logged.sum()
            value -= dropped.value.sum()
        if pid == "P06" and month == "2026-05":
            value += 3 * 900  # over-billed: architect days charged twice
            days += 3
        rows.append({"invoice_id": f"INV-{pid}-{month.replace('-', '')}", "project_id": pid, "month": month,
                     "days_invoiced": int(days), "amount_gbp": int(value)})
    return pd.DataFrame(rows)


def build_risks(projects, rng) -> pd.DataFrame:
    rows, n = [], 0
    as_of = pd.Timestamp("2026-09-30")
    severity = {"P03": 1.6, "P07": 1.4, "P05": 1.3, "P02": 1.15}
    for p in projects.itertuples():
        k = int(rng.integers(3, 7))
        for idx in rng.choice(len(RISK_LIBRARY), k, replace=False):
            n += 1
            title, cat = RISK_LIBRARY[idx]
            w = severity.get(p.project_id, 1.0)
            prob = int(np.clip(round(rng.integers(1, 5) * w), 1, 5))
            imp = int(np.clip(round(rng.integers(2, 5) * w), 1, 5))
            raised = pd.Timestamp("2026-01-15") + pd.Timedelta(days=int(rng.integers(0, 240)))
            due = raised + pd.Timedelta(days=int(rng.integers(20, 90)))
            status = rng.choice(["Open", "Mitigating", "Closed"], p=[0.45, 0.35, 0.20])
            if status != "Closed" and rng.random() < 0.65:
                due = as_of + pd.Timedelta(days=int(rng.integers(7, 60)))  # action still in date
            elif status != "Closed":
                due = max(raised + pd.Timedelta(days=14), as_of - pd.Timedelta(days=int(rng.integers(5, 70))))
            elif due > as_of + pd.Timedelta(days=60):
                due = as_of + pd.Timedelta(days=int(rng.integers(5, 60)))
            rows.append({"risk_id": f"RK{n:03d}", "project_id": p.project_id, "title": title, "category": cat,
                         "probability": prob, "impact": imp,
                         "owner": p.project_manager if rng.random() < 0.7 else rng.choice(RISK_OWNERS), "status": status,
                         "raised_date": raised.date().isoformat(), "action_due_date": due.date().isoformat()})
    return pd.DataFrame(rows)


def main() -> None:
    rng = np.random.default_rng(SEED)
    DATA_DIR.mkdir(exist_ok=True)
    projects = build_projects()
    evm = build_evm(projects, rng)
    resources = build_resources(rng)
    allocations = build_allocations(projects, resources, rng)
    timesheets = build_timesheets(allocations, rng)
    sows = build_sows(projects)
    invoices = build_invoices(timesheets, resources, sows, rng)
    risks = build_risks(projects, rng)

    outputs = {
        "projects.csv": projects.drop(columns=["target_cpi", "target_spi"]),
        "evm_monthly.csv": evm,
        "resources.csv": resources,
        "allocations.csv": allocations,
        "timesheets.csv": timesheets,
        "sows.csv": sows,
        "invoices.csv": invoices,
        "risks.csv": risks,
    }
    for name, df in outputs.items():
        df.to_csv(DATA_DIR / name, index=False)
        print(f"  wrote {name:<18} {len(df):>5} rows")


if __name__ == "__main__":
    main()
