"""Unit tests for the metrics engine. Run with:  pytest -q"""

import pandas as pd
import pytest

from pmo.metrics import (add_evm_indices, billing_reconciliation, load_portfolio, portfolio_snapshot, rag_status,
                         risk_register, sow_cover, utilisation)
from pmo.report import status_report


@pytest.fixture(scope="module")
def pf():
    return load_portfolio()


# --- Earned value --------------------------------------------------------
def test_evm_formulas_on_a_known_example():
    evm = pd.DataFrame([{"project_id": "X", "month": "2026-01", "planned_value": 100_000,
                         "earned_value": 80_000, "actual_cost": 100_000}])
    projects = pd.DataFrame([{"project_id": "X", "budget_gbp": 500_000}])
    r = add_evm_indices(evm, projects).iloc[0]
    assert r.cpi == pytest.approx(0.80)          # £80k of work for £100k spent
    assert r.spi == pytest.approx(0.80)          # 80% of planned work done
    assert r.eac == pytest.approx(625_000)       # 500k / 0.8
    assert r.vac == pytest.approx(-125_000)      # forecast overspend
    assert r.tcpi == pytest.approx(420_000 / 400_000)


@pytest.mark.parametrize("cpi,spi,critical,expected", [
    (1.00, 1.00, 0, "Green"),
    (0.96, 0.95, 0, "Green"),
    (0.94, 1.02, 0, "Amber"),
    (1.00, 1.00, 1, "Amber"),   # a critical risk alone is enough
    (0.84, 1.00, 0, "Red"),
    (1.00, 0.80, 2, "Red"),
    (float("nan"), 1.0, 0, "Grey"),
])
def test_rag_rules(cpi, spi, critical, expected):
    assert rag_status(cpi, spi, critical) == expected


def test_snapshot_has_one_row_per_project(pf):
    snap = portfolio_snapshot(pf, "2026-09")
    assert len(snap) == len(pf.projects)
    assert snap.rag.isin(["Green", "Amber", "Red"]).all()


def test_planted_red_projects_are_flagged(pf):
    snap = portfolio_snapshot(pf, "2026-09").set_index("project_id")
    assert snap.loc["P03", "rag"] == "Red"
    assert snap.loc["P07", "rag"] == "Red"


def test_cumulative_values_never_go_backwards(pf):
    for _, g in pf.evm.sort_values("month").groupby("project_id"):
        assert g.earned_value.is_monotonic_increasing
        assert g.actual_cost.is_monotonic_increasing


# --- Billing -------------------------------------------------------------
def test_sow_cover_statuses(pf):
    assert sow_cover(pf.sows, "P05", "2026-08")[0] == "Pending signature"
    assert sow_cover(pf.sows, "P07", "2026-08")[0] == "Expired"
    assert sow_cover(pf.sows, "P01", "2026-03")[0] == "Signed"


def test_reconciliation_finds_every_planted_issue(pf):
    r = billing_reconciliation(pf, "2026-09")
    found = set(zip(r.project_id, r.month, r.finding))
    assert ("P02", "2026-08", "Under-invoiced") in found
    assert ("P06", "2026-05", "Over-invoiced") in found
    assert {("P05", m, "Work on unsigned SOW") for m in ["2026-07", "2026-08", "2026-09"]} <= found
    assert {("P07", m, "Work after SOW expired") for m in ["2026-07", "2026-08", "2026-09"]} <= found


def test_reconciliation_has_no_false_alarms(pf):
    r = billing_reconciliation(pf, "2026-09")
    exceptions = r[r.finding != "Matched"]
    assert set(exceptions.project_id) == {"P02", "P05", "P06", "P07"}


# --- Resources & risks ---------------------------------------------------
def test_utilisation_is_days_over_capacity(pf):
    u = utilisation(pf, "2026-09")
    row = u.iloc[0]
    assert row.utilisation == pytest.approx(row.allocated_days / row.capacity_days)
    assert (u[u.utilisation > 1].flag == "Over-allocated").all()


def test_risk_register_respects_as_of_date(pf):
    early = risk_register(pf.risks, "2026-02")
    assert (early.raised_date <= pd.Timestamp("2026-02-28")).all()
    assert len(early) < len(risk_register(pf.risks, "2026-09"))


def test_status_report_builds_for_every_month(pf):
    for m in pf.months:
        text = status_report(pf, m)
        assert text.startswith("# Northwind")
        assert "## Decisions requested" in text
