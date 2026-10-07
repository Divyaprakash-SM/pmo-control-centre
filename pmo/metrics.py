"""
PMO metrics engine.

Pure functions: DataFrames in, DataFrames out. No Streamlit here, so every
calculation can be unit-tested and reused (e.g. in a scheduled report).

Plain-English cheat sheet for Earned Value Management (EVM):

  PV  Planned Value  - the work we *planned* to have done by now, in £
  EV  Earned Value   - the work we have *actually* done by now, in £ of budget
  AC  Actual Cost    - what we have *spent* to get that work done

  CPI = EV / AC   cost efficiency.     0.80 => every £1 spent buys 80p of work
  SPI = EV / PV   schedule efficiency. 0.90 => we have done 90% of planned work
  EAC = BAC / CPI forecast final cost if current efficiency continues
  VAC = BAC - EAC forecast overspend (negative) or underspend (positive)
  TCPI = (BAC - EV) / (BAC - AC)  efficiency needed on remaining work to land on budget
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# RAG thresholds - one place to change policy.
GREEN_MIN = 0.95   # CPI and SPI at or above this => on track
RED_BELOW = 0.85   # either index below this => intervention needed
HIGH_RISK_SCORE = 15      # probability x impact on a 5x5 matrix: escalate
CRITICAL_RISK_SCORE = 20  # an open risk this severe turns a project Amber on its own
OVER_ALLOCATED = 1.00
UNDER_UTILISED = 0.60


@dataclass
class Portfolio:
    projects: pd.DataFrame
    evm: pd.DataFrame
    resources: pd.DataFrame
    allocations: pd.DataFrame
    timesheets: pd.DataFrame
    sows: pd.DataFrame
    invoices: pd.DataFrame
    risks: pd.DataFrame

    @property
    def months(self) -> list[str]:
        return sorted(self.evm.month.unique())


def load_portfolio(data_dir: Path = DATA_DIR) -> Portfolio:
    read = lambda name: pd.read_csv(data_dir / f"{name}.csv")
    risks = read("risks")
    risks["raised_date"] = pd.to_datetime(risks.raised_date)
    risks["action_due_date"] = pd.to_datetime(risks.action_due_date)
    return Portfolio(read("projects"), read("evm_monthly"), read("resources"), read("allocations"),
                     read("timesheets"), read("sows"), read("invoices"), risks)


def month_end(month: str) -> pd.Timestamp:
    return pd.Period(month, "M").to_timestamp(how="end").normalize()


# ---------------------------------------------------------------------------
# Earned value & RAG
# ---------------------------------------------------------------------------
def add_evm_indices(evm: pd.DataFrame, projects: pd.DataFrame) -> pd.DataFrame:
    df = evm.merge(projects[["project_id", "budget_gbp"]], on="project_id")
    df["cpi"] = df.earned_value / df.actual_cost.replace(0, np.nan)
    df["spi"] = df.earned_value / df.planned_value.replace(0, np.nan)
    df["eac"] = df.budget_gbp / df.cpi
    df["vac"] = df.budget_gbp - df.eac
    df["etc"] = df.eac - df.actual_cost
    remaining_budget = (df.budget_gbp - df.actual_cost).replace(0, np.nan)
    df["tcpi"] = (df.budget_gbp - df.earned_value) / remaining_budget
    df["pct_complete"] = df.earned_value / df.budget_gbp
    return df


def rag_status(cpi: float, spi: float, critical_risks: int = 0) -> str:
    """Red if either index < 0.85; Amber if either < 0.95 or a critical (20+) risk is open; else Green."""
    if pd.isna(cpi) or pd.isna(spi):
        return "Grey"
    worst = min(cpi, spi)
    if worst < RED_BELOW:
        return "Red"
    if worst < GREEN_MIN or critical_risks > 0:
        return "Amber"
    return "Green"


def risk_register(risks: pd.DataFrame, as_of: str) -> pd.DataFrame:
    """Risks known at the as-of date, with score, band and overdue flag."""
    cutoff = month_end(as_of)
    df = risks[risks.raised_date <= cutoff].copy()
    df["score"] = df.probability * df.impact
    df["band"] = pd.cut(df.score, [0, 6, 14, 25], labels=["Low", "Medium", "High"])
    df["overdue"] = (df.status != "Closed") & (df.action_due_date < cutoff)
    df["days_overdue"] = np.where(df.overdue, (cutoff - df.action_due_date).dt.days, 0)
    return df


def portfolio_snapshot(pf: Portfolio, as_of: str) -> pd.DataFrame:
    """One row per project at the as-of month: EVM, risks, RAG."""
    evm = add_evm_indices(pf.evm, pf.projects)
    snap = evm[evm.month == as_of]
    risks = risk_register(pf.risks, as_of)
    open_risks = risks[risks.status != "Closed"]
    rc = open_risks.groupby("project_id").agg(open_risks=("risk_id", "count"),
                                             high_risks=("score", lambda s: int((s >= HIGH_RISK_SCORE).sum())),
                                             critical_risks=("score", lambda s: int((s >= CRITICAL_RISK_SCORE).sum())),
                                             overdue_actions=("overdue", "sum"))
    df = pf.projects.merge(snap.drop(columns="budget_gbp"), on="project_id", how="left").merge(
        rc, on="project_id", how="left")
    counts = ["open_risks", "high_risks", "critical_risks", "overdue_actions"]
    df[counts] = df[counts].fillna(0).astype(int)
    df["rag"] = [rag_status(c, s, k) for c, s, k in zip(df.cpi, df.spi, df.critical_risks)]
    return df


def project_trend(pf: Portfolio, project_id: str, as_of: str) -> pd.DataFrame:
    evm = add_evm_indices(pf.evm, pf.projects)
    return evm[(evm.project_id == project_id) & (evm.month <= as_of)].sort_values("month")


def portfolio_trend(pf: Portfolio, as_of: str) -> pd.DataFrame:
    """Portfolio-level CPI/SPI per month (budget-weighted via summed EV/AC/PV)."""
    g = pf.evm[pf.evm.month <= as_of].groupby("month")[["planned_value", "earned_value", "actual_cost"]].sum()
    g["cpi"] = g.earned_value / g.actual_cost
    g["spi"] = g.earned_value / g.planned_value
    return g.reset_index()


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------
def utilisation(pf: Portfolio, as_of: str) -> pd.DataFrame:
    """Allocated days / capacity per person per month."""
    a = pf.allocations[pf.allocations.month <= as_of]
    u = a.groupby(["resource_id", "month"], as_index=False).allocated_days.sum()
    u = u.merge(pf.resources, on="resource_id")
    u["utilisation"] = u.allocated_days / u.capacity_days
    u["flag"] = np.select([u.utilisation > OVER_ALLOCATED, u.utilisation < UNDER_UTILISED],
                          ["Over-allocated", "Under-utilised"], "OK")
    return u


def resource_exceptions(pf: Portfolio, as_of: str) -> pd.DataFrame:
    u = utilisation(pf, as_of)
    cur = u[u.month == as_of]
    projects = (pf.allocations[pf.allocations.month == as_of]
                .groupby("resource_id").project_id.apply(lambda s: ", ".join(sorted(s))))
    out = cur[cur.flag != "OK"].assign(projects=lambda d: d.resource_id.map(projects))
    # How many consecutive months has this person been in the same state?
    streak = []
    for r in out.itertuples():
        hist = u[u.resource_id == r.resource_id].sort_values("month", ascending=False)
        streak.append(int((hist.flag == r.flag).cumprod().sum()))
    out["months_in_state"] = streak
    return out.sort_values("utilisation", ascending=False)


# ---------------------------------------------------------------------------
# Billing reconciliation  (timesheets x rates  vs  invoices  vs  SOW cover)
# ---------------------------------------------------------------------------
def sow_cover(sows: pd.DataFrame, project_id: str, month: str) -> tuple[str, str]:
    """Return (status, sow_id) of the SOW covering this project-month, if any."""
    m = pd.Period(month, "M")
    s = sows[sows.project_id == project_id]
    s = s[s.start_month.map(lambda x: pd.Period(x, "M") <= m) & s.end_month.map(lambda x: pd.Period(x, "M") >= m)]
    if s.empty:
        lapsed = sows[(sows.project_id == project_id) & sows.end_month.map(lambda x: pd.Period(x, "M") < m)]
        return ("Expired", lapsed.iloc[-1].sow_id) if not lapsed.empty else ("No SOW", "")
    signed = s[s.status == "Signed"]
    row = signed.iloc[0] if not signed.empty else s.iloc[0]
    return row.status, row.sow_id


def billing_reconciliation(pf: Portfolio, as_of: str, tolerance_gbp: float = 500) -> pd.DataFrame:
    ts = pf.timesheets[pf.timesheets.month <= as_of].merge(pf.resources[["resource_id", "day_rate_gbp"]], on="resource_id")
    ts["billable_gbp"] = ts.days_logged * ts.day_rate_gbp
    exp = ts.groupby(["project_id", "month"], as_index=False).agg(days_logged=("days_logged", "sum"),
                                                                 billable_gbp=("billable_gbp", "sum"))
    inv = pf.invoices[pf.invoices.month <= as_of]
    df = exp.merge(inv[["project_id", "month", "invoice_id", "days_invoiced", "amount_gbp"]],
                   on=["project_id", "month"], how="left")
    df[["days_invoiced", "amount_gbp"]] = df[["days_invoiced", "amount_gbp"]].fillna(0)
    df["gap_gbp"] = df.billable_gbp - df.amount_gbp  # +ve => revenue not billed
    cover = [sow_cover(pf.sows, p, m) for p, m in zip(df.project_id, df.month)]
    df["sow_status"] = [c[0] for c in cover]
    df["sow_id"] = [c[1] for c in cover]

    def classify(r) -> str:
        if r.sow_status != "Signed":
            return {"Pending signature": "Work on unsigned SOW", "Expired": "Work after SOW expired"}.get(
                r.sow_status, "Work with no SOW")
        if abs(r.gap_gbp) <= tolerance_gbp:
            return "Matched"
        return "Under-invoiced" if r.gap_gbp > 0 else "Over-invoiced"

    df["finding"] = df.apply(classify, axis=1)
    return df.merge(pf.projects[["project_id", "project_name"]], on="project_id")


# ---------------------------------------------------------------------------
# Plain-English commentary - what a PMO analyst would write in the status pack
# ---------------------------------------------------------------------------
def gbp(x: float) -> str:
    sign = "-" if x < 0 else ""
    x = abs(x)
    return f"{sign}£{x/1e6:.2f}m" if x >= 1e6 else f"{sign}£{x/1e3:.0f}k"


def project_commentary(row: pd.Series, recon: pd.DataFrame) -> list[str]:
    notes = []
    pence = round(row.cpi * 100)
    if row.cpi < GREEN_MIN:
        notes.append(f"Cost: every £1 spent is delivering {pence}p of planned work. "
                     f"If that continues the project lands at {gbp(row.eac)} against a {gbp(row.budget_gbp)} budget "
                     f"({gbp(-row.vac)} over).")
    else:
        side = "under" if row.vac >= 0 else "over"
        notes.append(f"Cost: within tolerance (CPI {row.cpi:.2f}). Forecast outturn {gbp(row.eac)}, "
                     f"{gbp(abs(row.vac))} {side} budget.")
    if row.spi < GREEN_MIN:
        notes.append(f"Schedule: {row.spi:.0%} of the work planned by now is complete.")
    else:
        notes.append(f"Schedule: on track ({row.spi:.0%} of planned work complete).")
    if row.tcpi > 1.10 and row.cpi < GREEN_MIN:
        notes.append(f"Recovery: the remaining work would need to run at {row.tcpi:.2f} efficiency to land on budget - "
                     "not realistic without re-baselining or a change request.")
    if row.high_risks:
        notes.append(f"Risk: {row.high_risks} high-scoring risk(s) open.")
    if row.overdue_actions:
        notes.append(f"Governance: {row.overdue_actions} risk action(s) past due date.")
    mine = recon[recon.project_id == row.project_id]
    for finding, g in mine[mine.finding != "Matched"].groupby("finding"):
        months = ", ".join(pd.Period(m, "M").strftime("%b") for m in sorted(g.month))
        if finding == "Over-invoiced":
            notes.append(f"Billing: client over-billed by {gbp(-g.gap_gbp.sum())} ({months}). Credit note needed.")
        else:
            notes.append(f"Billing: {gbp(g.gap_gbp.sum())} of logged effort not invoiced ({finding}; {months}).")
    return notes
