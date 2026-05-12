"""
dashboard.py — Streamlit Sales Dashboard
Run: streamlit run dashboard/dashboard.py
"""
import streamlit as st
import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "warehouse.duckdb"

st.set_page_config(
    page_title="Sales Pipeline Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ── Styling ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');
    html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
    .metric-card {
        background: #0f0f0f; border: 1px solid #2a2a2a;
        border-radius: 8px; padding: 20px 24px;
    }
    .dq-pass { color: #00d17a; font-weight: 600; }
    .dq-fail { color: #ff4757; font-weight: 600; }
    .dq-warn { color: #ffa502; font-weight: 600; }
    h1 { font-family: 'IBM Plex Mono', monospace !important; letter-spacing: -1px; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_con():
    return duckdb.connect(str(DB_PATH), read_only=True)


def q(sql):
    try:
        return get_con().execute(sql).df()
    except Exception as e:
        st.error(f"Query error: {e}")
        return pd.DataFrame()


# ── Header ───────────────────────────────────────────────────────────────────
st.title("📊 Sales Pipeline")
st.caption("Single source of truth · March 2025 · Auto-refreshes on reload")

# ── KPIs ─────────────────────────────────────────────────────────────────────
kpi = q("""
SELECT
    SUM(net_revenue)       AS total_revenue,
    SUM(order_count)       AS total_orders,
    SUM(unique_customers)  AS total_customers,
    ROUND(AVG(avg_order_value), 2) AS avg_order_value
FROM fct_daily_revenue
""")

if not kpi.empty:
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Total Net Revenue", f"${kpi['total_revenue'][0]:,.0f}")
    with c2:
        st.metric("Total Orders", f"{kpi['total_orders'][0]:,}")
    with c3:
        st.metric("Unique Customers", f"{kpi['total_customers'][0]:,}")
    with c4:
        st.metric("Avg Order Value", f"${kpi['avg_order_value'][0]:,.2f}")

st.divider()

# ── Daily Revenue Chart ───────────────────────────────────────────────────────
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Daily Net Revenue")
    daily = q("SELECT * FROM fct_daily_revenue ORDER BY sale_date")
    if not daily.empty:
        fig = px.area(
            daily, x="sale_date", y="net_revenue",
            color_discrete_sequence=["#00d17a"],
            template="plotly_dark"
        )
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=0, b=0),
            xaxis_title="", yaxis_title="Net Revenue ($)"
        )
        fig.update_traces(fillcolor="rgba(0,209,122,0.15)")
        st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Revenue by Region")
    region = q("SELECT * FROM fct_region_summary ORDER BY net_revenue DESC")
    if not region.empty:
        fig2 = px.bar(
            region, x="net_revenue", y="region", orientation="h",
            color="net_revenue", color_continuous_scale="Teal",
            template="plotly_dark"
        )
        fig2.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            showlegend=False, coloraxis_showscale=False,
            margin=dict(l=0, r=0, t=0, b=0),
            xaxis_title="Net Revenue ($)", yaxis_title=""
        )
        st.plotly_chart(fig2, use_container_width=True)

st.divider()

# ── Top Products ──────────────────────────────────────────────────────────────
col3, col4 = st.columns([1, 1])

with col3:
    st.subheader("Top Products by Revenue")
    prods = q("SELECT product_name, net_revenue, total_units_sold, avg_discount_pct FROM fct_product_summary LIMIT 12")
    if not prods.empty:
        fig3 = px.bar(
            prods, x="net_revenue", y="product_name", orientation="h",
            color="avg_discount_pct", color_continuous_scale="RdYlGn_r",
            template="plotly_dark",
            hover_data=["total_units_sold", "avg_discount_pct"]
        )
        fig3.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=0, b=0),
            xaxis_title="Net Revenue ($)", yaxis_title="",
            coloraxis_colorbar=dict(title="Avg Disc %")
        )
        st.plotly_chart(fig3, use_container_width=True)

with col4:
    st.subheader("Category Mix")
    cat = q("""
    SELECT category,
           SUM(net_revenue) AS revenue,
           SUM(total_units_sold) AS units
    FROM fct_product_summary GROUP BY 1 ORDER BY 2 DESC
    """)
    if not cat.empty:
        fig4 = px.pie(
            cat, values="revenue", names="category",
            hole=0.55, template="plotly_dark",
            color_discrete_sequence=px.colors.qualitative.Safe
        )
        fig4.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=0, b=0)
        )
        st.plotly_chart(fig4, use_container_width=True)

st.divider()

# ── Data Quality Panel ────────────────────────────────────────────────────────
st.subheader("🔍 Data Quality Status")

dq = q("""
SELECT check, status, detail, file,
       MAX(run_ts) AS last_run
FROM dq_log
GROUP BY 1,2,3,4
ORDER BY CASE status WHEN 'FAIL' THEN 0 WHEN 'WARN' THEN 1 ELSE 2 END, check
""")

if not dq.empty:
    fails = dq[dq["status"] == "FAIL"]
    warns = dq[dq["status"] == "WARN"]
    passes = dq[dq["status"] == "PASS"]

    c1, c2, c3 = st.columns(3)
    c1.metric("❌ Failures", len(fails))
    c2.metric("⚠️ Warnings", len(warns))
    c3.metric("✅ Passing", len(passes))

    def color_status(val):
        colors = {"FAIL": "#ff4757", "WARN": "#ffa502", "PASS": "#00d17a"}
        return f"color: {colors.get(val, 'white')}; font-weight: 600"

    styled = dq[["check", "status", "detail", "file"]].style.applymap(
        color_status, subset=["status"]
    )
    st.dataframe(styled, use_container_width=True, height=300)
else:
    st.info("No DQ log found. Run the pipeline first.")

st.divider()

# ── Raw data explorer ─────────────────────────────────────────────────────────
with st.expander("📋 Daily Revenue Table"):
    daily_tbl = q("SELECT * FROM fct_daily_revenue ORDER BY sale_date")
    st.dataframe(daily_tbl, use_container_width=True)

with st.expander("🛍️ Product Detail Table"):
    prod_tbl = q("SELECT * FROM fct_product_summary ORDER BY net_revenue DESC")
    st.dataframe(prod_tbl, use_container_width=True)

st.caption("Pipeline by Pranayak Uniyal · DuckDB + Streamlit · Data: March 2025")
