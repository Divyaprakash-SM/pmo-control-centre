"""
PMO Control Centre: Streamlit dashboard.

Run locally:  streamlit run app.py
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from pmo.metrics import (CRITICAL_RISK_SCORE, GREEN_MIN, eac_scenarios, forecast_finish, HIGH_RISK_SCORE, RED_BELOW, billing_reconciliation, gbp, load_portfolio,
                         portfolio_snapshot, portfolio_trend, project_commentary, project_trend,
                         resource_exceptions, risk_register, utilisation)
from pmo.report import status_report

st.set_page_config(page_title="PMO Control Centre", page_icon="📊", layout="wide")

# ---------------------------------------------------------------------------
# Visual system: status colours are reserved for RAG; series colours for data.
# ---------------------------------------------------------------------------
RAG = {"Green": "#0ca30c", "Amber": "#fab219", "Red": "#d03b3b", "Grey": "#9a9993"}
RAG_ICON = {"Green": "🟢", "Amber": "🟠", "Red": "🔴", "Grey": "⚪"}
SERIES = {"pv": "#2a78d6", "ev": "#eb6834", "ac": "#1baf7a"}
BLUES = ["#f0efec", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e6e5e0"

st.markdown("""
<style>
  .block-container {padding-top: 2rem; max-width: 1400px;}
  [data-testid="stMetricValue"] {font-size: 1.7rem; font-weight: 650;}
  [data-testid="stMetricLabel"] p {font-size: .8rem; text-transform: uppercase; letter-spacing: .04em; color: #52514e;}
  .rag-pill {display:inline-block; padding:2px 10px; border-radius:999px; font-size:.8rem; font-weight:600; color:#0b0b0b;}
  .note {font-size:.85rem; color:#52514e;}
  h1 {font-weight: 700; letter-spacing: -.02em;}
</style>
""", unsafe_allow_html=True)


def style(fig: go.Figure, height: int = 360, **kw) -> go.Figure:
    fig.update_layout(template="plotly_white", height=height, margin=dict(l=10, r=10, t=40, b=10),
                      font=dict(family="Inter, Segoe UI, sans-serif", size=13, color=INK),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None),
                      hoverlabel=dict(bgcolor="white", font_size=12), **kw)
    fig.update_xaxes(showgrid=False, linecolor=GRID, tickfont=dict(color=MUTED))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, tickfont=dict(color=MUTED))
    return fig


def pill(rag: str) -> str:
    return f'<span class="rag-pill" style="background:{RAG[rag]}33;border:1px solid {RAG[rag]}">{RAG_ICON[rag]} {rag}</span>'


@st.cache_data
def data():
    return load_portfolio()


pf = data()

# ---------------------------------------------------------------------------
# Sidebar: reporting period + filters
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Reporting period")
    as_of = st.select_slider("As of month end", options=pf.months, value=pf.months[-1],
                             format_func=lambda m: pd.Period(m, "M").strftime("%b %Y"))
    st.caption("Slide back to replay the portfolio as it looked at any earlier month end.")
    workstreams = st.multiselect("Workstream", sorted(pf.projects.workstream.unique()))
    st.divider()
    st.markdown("**RAG rules**")
    st.caption(f"🔴 Red: CPI or SPI below {RED_BELOW}\n\n"
               f"🟠 Amber: CPI or SPI below {GREEN_MIN}, or a risk scoring {CRITICAL_RISK_SCORE}+ is open\n\n"
               f"🟢 Green: everything else")
    st.divider()
    st.caption("All data is synthetic. Northwind Utilities is a fictional client.")

snap = portfolio_snapshot(pf, as_of)
recon = billing_reconciliation(pf, as_of)
risks = risk_register(pf.risks, as_of).merge(pf.projects[["project_id", "project_name", "workstream"]])
if workstreams:
    keep = pf.projects[pf.projects.workstream.isin(workstreams)].project_id
    snap, recon, risks = (d[d.project_id.isin(keep)] for d in (snap, recon, risks))

month_label = pd.Period(as_of, "M").strftime("%B %Y")
st.title("PMO Control Centre")
st.markdown(f"<p class='note'>Northwind Utilities Transformation Programme · {len(snap)} projects · "
            f"position at end of <b>{month_label}</b></p>", unsafe_allow_html=True)

tab_overview, tab_project, tab_people, tab_risk, tab_billing, tab_report = st.tabs(
    ["Portfolio", "Project deep dive", "Resources", "Risks", "Billing reconciliation", "Status report"])

# ===========================================================================
# 1. PORTFOLIO
# ===========================================================================
with tab_overview:
    bac, eac = snap.budget_gbp.sum(), snap.eac.sum()
    leakage = recon[recon.finding != "Matched"].gap_gbp.clip(lower=0).sum()
    high_open = int(((risks.score >= HIGH_RISK_SCORE) & (risks.status != "Closed")).sum())
    counts = snap.rag.value_counts()

    c = st.columns(5)
    c[0].metric("Total budget", gbp(bac))
    c[1].metric("Forecast outturn", gbp(eac), f"{gbp(eac - bac)} vs budget", delta_color="inverse")
    c[2].metric("Projects Red / Amber", f"{counts.get('Red', 0)} / {counts.get('Amber', 0)}")
    c[3].metric("Revenue not invoiced", gbp(leakage))
    c[4].metric("High risks open", high_open, f"{int(risks.overdue.sum())} actions overdue", delta_color="off", delta_arrow="off")

    left, right = st.columns([1.15, 1])
    with left:
        st.subheader("Where each project sits")
        fig = go.Figure()
        fig.add_shape(type="rect", x0=0.7, x1=GREEN_MIN, y0=0.7, y1=GREEN_MIN, fillcolor="#d03b3b", opacity=.05, line_width=0)
        fig.add_hline(y=1, line=dict(color=MUTED, width=1, dash="dot"))
        fig.add_vline(x=1, line=dict(color=MUTED, width=1, dash="dot"))
        for rag in ["Red", "Amber", "Green"]:
            g = snap[snap.rag == rag]
            if g.empty:
                continue
            fig.add_trace(go.Scatter(
                x=g.cpi, y=g.spi, mode="markers+text", name=rag, text=g.project_id, textposition="top center",
                marker=dict(size=g.budget_gbp / 1e5 + 12, color=RAG[rag], opacity=.85, line=dict(color="white", width=2)),
                customdata=g[["project_name", "budget_gbp", "eac"]],
                hovertemplate="<b>%{customdata[0]}</b><br>CPI %{x:.2f} · SPI %{y:.2f}"
                              "<br>Budget £%{customdata[1]:,.0f}<br>Forecast £%{customdata[2]:,.0f}<extra></extra>"))
        fig.add_annotation(x=0.705, y=1.095, text="Right of dotted line = under budget<br>Above dotted line = ahead of schedule",
                           showarrow=False, xanchor="left", yanchor="top", align="left", font=dict(color=MUTED, size=11))
        fig.add_annotation(x=0.76, y=0.74, text="Behind & over budget", showarrow=False, font=dict(color=MUTED, size=11))
        style(fig, 420, xaxis_title="Cost efficiency (CPI)", yaxis_title="Schedule efficiency (SPI)")
        fig.update_xaxes(range=[0.7, 1.1]); fig.update_yaxes(range=[0.7, 1.1])
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Bubble size = budget. 1.00 means exactly on plan; below 1.00 means behind or over budget.")
    with right:
        st.subheader("Portfolio efficiency trend")
        tr = portfolio_trend(pf, as_of)
        fig = go.Figure()
        fig.add_hrect(y0=RED_BELOW, y1=GREEN_MIN, fillcolor="#fab219", opacity=.08, line_width=0)
        fig.add_trace(go.Scatter(x=tr.month, y=tr.cpi, name="CPI (cost)", line=dict(color=SERIES["pv"], width=2),
                                 mode="lines+markers", marker=dict(size=8)))
        fig.add_trace(go.Scatter(x=tr.month, y=tr.spi, name="SPI (schedule)", line=dict(color=SERIES["ev"], width=2),
                                 mode="lines+markers", marker=dict(size=8)))
        style(fig, 420, hovermode="x unified")
        fig.update_yaxes(range=[0.8, 1.05], tickformat=".2f")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Shaded band = Amber zone. The whole programme is drifting: cost efficiency is falling month on month.")

    st.subheader("Project register")
    view = snap.sort_values("rag", key=lambda s: s.map({"Red": 0, "Amber": 1, "Green": 2, "Grey": 3}))
    st.dataframe(
        view.assign(RAG=view.rag.map(lambda r: f"{RAG_ICON[r]} {r}"))[
            ["RAG", "project_id", "project_name", "workstream", "project_manager", "budget_gbp", "eac", "vac",
             "pct_complete", "cpi", "spi", "open_risks", "overdue_actions"]],
        hide_index=True, use_container_width=True,
        column_config={
            "project_id": "ID", "project_name": "Project", "workstream": "Workstream", "project_manager": "PM",
            "budget_gbp": st.column_config.NumberColumn("Budget", format="£%d"),
            "eac": st.column_config.NumberColumn("Forecast (EAC)", format="£%d"),
            "vac": st.column_config.NumberColumn("Variance (VAC)", format="£%d"),
            "pct_complete": st.column_config.ProgressColumn("% complete", format="%.0f%%", min_value=0, max_value=1),
            "cpi": st.column_config.NumberColumn("CPI", format="%.2f"),
            "spi": st.column_config.NumberColumn("SPI", format="%.2f"),
            "open_risks": "Open risks", "overdue_actions": "Overdue actions"})

# ===========================================================================
# 2. PROJECT DEEP DIVE
# ===========================================================================
with tab_project:
    options = snap.assign(_o=snap.rag.map({"Red": 0, "Amber": 1, "Green": 2, "Grey": 3})).sort_values(["_o", "project_id"])
    pid = st.selectbox("Project (worst first)", options.project_id,
                       format_func=lambda p: f"{p} · {options.set_index('project_id').project_name[p]}")
    row = snap.set_index("project_id").loc[pid]
    st.markdown(f"### {row.project_name} &nbsp; {pill(row.rag)}", unsafe_allow_html=True)
    st.markdown(f"<p class='note'>{row.workstream} · PM: {row.project_manager} · "
                f"{pd.Period(row.start_month,'M').strftime('%b %Y')} to {pd.Period(row.end_month,'M').strftime('%b %Y')}</p>",
                unsafe_allow_html=True)

    c = st.columns(6)
    c[0].metric("Budget (BAC)", gbp(row.budget_gbp))
    c[1].metric("Spent (AC)", gbp(row.actual_cost))
    c[2].metric("Forecast (EAC)", gbp(row.eac), f"{gbp(-row.vac)} vs budget", delta_color="inverse")
    c[3].metric("CPI", f"{row.cpi:.2f}")
    c[4].metric("SPI", f"{row.spi:.2f}")
    c[5].metric("TCPI", f"{row.tcpi:.2f}", help="Efficiency the remaining work must achieve to finish on budget.")

    left, right = st.columns([1.4, 1])
    with left:
        tr = project_trend(pf, pid, as_of)
        fig = go.Figure()
        for col, name, key in [("planned_value", "Planned (PV)", "pv"), ("earned_value", "Earned (EV)", "ev"),
                               ("actual_cost", "Actual cost (AC)", "ac")]:
            fig.add_trace(go.Scatter(x=tr.month, y=tr[col], name=name, mode="lines+markers",
                                     line=dict(color=SERIES[key], width=2), marker=dict(size=7),
                                     hovertemplate=f"{name}: £%{{y:,.0f}}<extra></extra>"))
        fig.add_hline(y=row.budget_gbp, line=dict(color=MUTED, dash="dash", width=1),
                      annotation_text="Budget", annotation_position="top left")
        st.markdown("#### Earned value S-curve")
        style(fig, 380, hovermode="x unified")
        fig.update_yaxes(tickprefix="£", tickformat=".2s")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Earned below Planned = behind schedule. Actual above Earned = paying more than the work is worth.")
    with right:
        st.markdown("#### What this means")
        for note in project_commentary(snap[snap.project_id == pid].iloc[0], recon):
            st.markdown(f"- {note}")
        st.markdown("#### Open risks")
        pr = risks[(risks.project_id == pid) & (risks.status != "Closed")].sort_values("score", ascending=False)
        st.dataframe(pr[["title", "score", "owner", "action_due_date", "overdue"]], hide_index=True,
                     use_container_width=True,
                     column_config={"title": "Risk", "score": "Score", "owner": "Owner",
                                    "action_due_date": st.column_config.DateColumn("Action due", format="DD MMM YYYY"),
                                    "overdue": st.column_config.CheckboxColumn("Overdue")})

    st.markdown("#### Forecast range: where will it land?")
    prow = snap[snap.project_id == pid].iloc[0]
    sc = eac_scenarios(prow)
    l2, r2 = st.columns([1.4, 1])
    with l2:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=[sc.eac.min(), sc.eac.max()], y=["Forecast"] * 2, mode="lines",
                                 line=dict(color=SERIES["pv"], width=8), opacity=0.25, showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=sc.eac, y=["Forecast"] * 3, mode="markers+text", text=["①", "②", "③"],
                                 textposition="top center", marker=dict(size=14, color=SERIES["pv"], line=dict(color="white", width=2)),
                                 customdata=sc[["scenario", "formula"]], showlegend=False,
                                 hovertemplate="%{customdata[0]}<br>%{customdata[1]} = £%{x:,.0f}<extra></extra>"))
        fig.add_vline(x=prow.budget_gbp, line=dict(color=INK, width=1.5, dash="dash"))
        fig.add_annotation(x=prow.budget_gbp, y=1, yref="paper", text="Budget", showarrow=False, xanchor="left",
                           font=dict(size=11, color=MUTED))
        lo_x = min(sc.eac.min(), prow.budget_gbp) * 0.97
        hi_x = max(sc.eac.max(), prow.budget_gbp) * 1.03
        style(fig, 170)
        fig.update_layout(margin=dict(l=10, r=10, t=20, b=10))
        fig.update_xaxes(tickprefix="£", tickformat=".3s", range=[lo_x, hi_x]); fig.update_yaxes(visible=False)
        st.plotly_chart(fig, use_container_width=True)
    with r2:
        fin = forecast_finish(prow)
        late = (fin - pd.Period(prow.end_month, "M")).n
        st.markdown("\n".join(f"- {i} **{r.scenario}:** {gbp(r.eac)}" for i, r in zip("①②③", sc.itertuples())))
        planned_end = pd.Period(prow.end_month, "M").strftime("%b %Y")
        verdict = "on plan" if late <= 0 else f"{late} month(s) after the planned {planned_end}"
        st.markdown(f"**Forecast finish:** {fin.strftime('%b %Y')} ({verdict}), based on duration ÷ SPI.")
    st.caption("The three standard PMBOK estimate-at-completion formulas. Each assumes a different future: problems "
               "were one-off (①), cost efficiency continues (②), or being late keeps costing money too (③). "
               "The spread between them is the honest range to report.")

# ===========================================================================
# 3. RESOURCES
# ===========================================================================
with tab_people:
    u = utilisation(pf, as_of)
    if workstreams:
        on_ws = pf.allocations[pf.allocations.project_id.isin(keep)].resource_id.unique()
        u = u[u.resource_id.isin(on_ws)]
    cur = u[u.month == as_of]
    c = st.columns(4)
    c[0].metric("People on programme", cur.resource_id.nunique())
    c[1].metric("Average utilisation", f"{cur.utilisation.mean():.0%}")
    c[2].metric("Over-allocated (>100%)", int((cur.flag == "Over-allocated").sum()))
    c[3].metric("Under-utilised (<60%)", int((cur.flag == "Under-utilised").sum()))

    st.subheader("Utilisation by person and month")
    piv = u.assign(label=u.name + " · " + u.role).pivot_table(index="label", columns="month", values="utilisation")
    piv = piv.loc[piv[as_of].sort_values(ascending=False).index] if as_of in piv else piv
    fig = go.Figure(go.Heatmap(
        z=piv.values, x=[pd.Period(m, "M").strftime("%b") for m in piv.columns], y=piv.index,
        colorscale=[[0, "#fdf1ec"], [0.45, "#f7f7f5"], [0.6, "#cde2fb"], [0.75, "#6da7ec"], [0.85, "#256abf"],
                    [1, "#0d366b"]],
        zmin=0, zmax=1.4, xgap=2, ygap=2,
        text=[[f"{v:.0%}" if pd.notna(v) else "" for v in r] for r in piv.values], texttemplate="%{text}",
        textfont=dict(size=10), hovertemplate="%{y}<br>%{x}: %{z:.0%}<extra></extra>",
        colorbar=dict(title="Util.", tickformat=".0%")))
    style(fig, max(420, 19 * len(piv)))
    fig.update_yaxes(autorange="reversed", tickfont=dict(size=11))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Sorted by current-month utilisation. Anything above 100% is a burnout and quality risk; "
               "below 60% is cost the client is paying for without output.")

    st.subheader("Exceptions to action this month")
    ex = resource_exceptions(pf, as_of)
    if workstreams:
        ex = ex[ex.resource_id.isin(on_ws)]
    st.dataframe(ex[["name", "role", "utilisation", "flag", "projects", "months_in_state"]], hide_index=True,
                 use_container_width=True,
                 column_config={"name": "Person", "role": "Role",
                                "utilisation": st.column_config.NumberColumn("Utilisation", format="percent"),
                                "flag": "Flag", "projects": "Booked on",
                                "months_in_state": st.column_config.NumberColumn("Months in this state")})

# ===========================================================================
# 4. RISKS
# ===========================================================================
with tab_risk:
    open_r = risks[risks.status != "Closed"]
    c = st.columns(4)
    c[0].metric("Open risks", len(open_r))
    c[1].metric(f"High (score {HIGH_RISK_SCORE}+)", int((open_r.score >= HIGH_RISK_SCORE).sum()))
    c[2].metric("Actions overdue", int(open_r.overdue.sum()))
    c[3].metric("Average days overdue", f"{open_r[open_r.overdue].days_overdue.mean():.0f}" if open_r.overdue.any() else "0")

    left, right = st.columns([1, 1.3])
    with left:
        st.subheader("Risk heat map")
        grid = open_r.groupby(["probability", "impact"]).size().unstack(fill_value=0).reindex(
            index=range(1, 6), columns=range(1, 6), fill_value=0)
        zone = [[(p * i) for i in range(1, 6)] for p in range(1, 6)]
        zcolor = [[0, "#e7f6e7"], [0.24, "#e7f6e7"], [0.25, "#fef3d6"], [0.56, "#fef3d6"], [0.57, "#f8dcdc"], [1, "#f8dcdc"]]
        fig = go.Figure(go.Heatmap(z=zone, x=list(range(1, 6)), y=list(range(1, 6)), colorscale=zcolor, showscale=False,
                                   xgap=3, ygap=3, text=[[str(v) if v else "" for v in r] for r in grid.values],
                                   texttemplate="<b>%{text}</b>", textfont=dict(size=18, color=INK),
                                   customdata=grid.values,
                                   hovertemplate="Probability %{y} × Impact %{x}<br>%{customdata} open risk(s)<extra></extra>"))
        style(fig, 380, xaxis_title="Impact →", yaxis_title="Probability →")
        fig.update_xaxes(dtick=1); fig.update_yaxes(dtick=1, showgrid=False)
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Number in each cell = open risks. Red zone = score 15+ (escalate to steering committee).")
    with right:
        st.subheader("Open risk exposure by project")
        by = open_r.groupby("project_name").agg(score=("score", "sum"), n=("risk_id", "count")).sort_values("score")
        fig = go.Figure(go.Bar(x=by.score, y=by.index, orientation="h", marker=dict(color="#2a78d6", cornerradius=4),
                               text=by.n.map(lambda n: f"{n} risk" + ("s" if n != 1 else "")), textposition="outside",
                               cliponaxis=False,
                               hovertemplate="%{y}<br>Total score %{x}<extra></extra>"))
        style(fig, 380, xaxis_title="Sum of risk scores")
        fig.update_xaxes(range=[0, by.score.max() * 1.2])
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Risk register")
    only_overdue = st.toggle("Show only overdue actions")
    reg = open_r[open_r.overdue] if only_overdue else risks
    st.dataframe(reg.sort_values(["overdue", "score"], ascending=False)[
        ["risk_id", "project_name", "title", "category", "probability", "impact", "score", "owner", "status",
         "action_due_date", "days_overdue"]], hide_index=True, use_container_width=True,
        column_config={"risk_id": "ID", "project_name": "Project", "title": "Risk", "category": "Category",
                       "probability": "P", "impact": "I", "score": "Score", "owner": "Owner", "status": "Status",
                       "action_due_date": st.column_config.DateColumn("Action due", format="DD MMM YYYY"),
                       "days_overdue": "Days overdue"})

# ===========================================================================
# 5. BILLING RECONCILIATION
# ===========================================================================
with tab_billing:
    st.markdown("Timesheet days × contracted day rates, checked against what was actually invoiced and whether "
                "a **signed SOW** covered the work. This is where revenue quietly leaks.")
    exc = recon[recon.finding != "Matched"]
    c = st.columns(4)
    c[0].metric("Billable effort logged", gbp(recon.billable_gbp.sum()))
    c[1].metric("Invoiced", gbp(recon.amount_gbp.sum()))
    c[2].metric("Not invoiced", gbp(exc.gap_gbp.clip(lower=0).sum()))
    c[3].metric("Exceptions", len(exc), f"{exc.project_id.nunique()} projects", delta_color="off", delta_arrow="off")

    left, right = st.columns([1, 1.2])
    with left:
        st.subheader("Unbilled revenue by cause")
        cause = exc[exc.gap_gbp > 0].groupby("finding").gap_gbp.sum().sort_values()
        fig = go.Figure(go.Bar(x=cause.values, y=cause.index, orientation="h",
                               marker=dict(color="#2a78d6", cornerradius=4),
                               text=[gbp(v) for v in cause.values], textposition="outside", cliponaxis=False,
                               hovertemplate="%{y}: £%{x:,.0f}<extra></extra>"))
        style(fig, 300)
        fig.update_xaxes(tickprefix="£", tickformat=".2s", range=[0, cause.max() * 1.25 if len(cause) else 1])
        st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("Logged vs invoiced, month by month")
        m = recon.groupby("month")[["billable_gbp", "amount_gbp"]].sum()
        fig = go.Figure()
        fig.add_trace(go.Bar(x=m.index, y=m.billable_gbp, name="Logged effort", marker=dict(color="#b7d3f6", cornerradius=4)))
        fig.add_trace(go.Bar(x=m.index, y=m.amount_gbp, name="Invoiced", marker=dict(color="#256abf", cornerradius=4)))
        style(fig, 300, barmode="group", bargap=.3, bargroupgap=.08, hovermode="x unified")
        fig.update_yaxes(tickprefix="£", tickformat=".2s")
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Exceptions")
    st.dataframe(exc.sort_values(["project_id", "month"])[
        ["project_id", "project_name", "month", "sow_id", "sow_status", "days_logged", "days_invoiced",
         "billable_gbp", "amount_gbp", "gap_gbp", "finding"]], hide_index=True, use_container_width=True,
        column_config={"project_id": "ID", "project_name": "Project", "month": "Month", "sow_id": "SOW",
                       "sow_status": "SOW status", "days_logged": "Days logged", "days_invoiced": "Days invoiced",
                       "billable_gbp": st.column_config.NumberColumn("Should bill", format="£%d"),
                       "amount_gbp": st.column_config.NumberColumn("Invoiced", format="£%d"),
                       "gap_gbp": st.column_config.NumberColumn("Gap", format="£%d"), "finding": "Finding"})
    st.download_button("Download exceptions (CSV)", exc.to_csv(index=False), f"billing_exceptions_{as_of}.csv",
                       "text/csv")

# ===========================================================================
# 6. STATUS REPORT
# ===========================================================================
with tab_report:
    report = status_report(pf, as_of)
    st.download_button("Download status report (Markdown)", report, f"status_report_{as_of}.md", "text/markdown",
                       type="primary")
    st.caption("Generated automatically from the same numbers as the dashboard. Paste into Word, Confluence or email.")
    with st.container(border=True):
        st.markdown(report.replace("\n# ", "\n## ").replace("# ", "## ", 1))
