import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

st.set_page_config(layout="wide", page_title="Insurance Reserving Model")
st.title("Insurance Reserving Model")
st.markdown("**Chain-Ladder + Bornhuetter-Ferguson | 50/50 Blend**")

# ── Sidebar ────────────────────────────────────────────────────────────────────
st.sidebar.header("Model Parameters")
valuation_year = st.sidebar.number_input("Valuation Year", value=2023, step=1)
tail_factor = st.sidebar.number_input("Tail Factor", min_value=1.0, max_value=10.0, value=1.0, step=0.01)
st.sidebar.markdown("---")
st.sidebar.subheader("Premium / BF Settings")
premium_source = st.sidebar.radio(
    "Premium Source for BF",
    ["Derive from data (mean CL ultimates)", "Enter manually"],
)
manual_premium = None
elr = None
if premium_source == "Enter manually":
    manual_premium = st.sidebar.number_input("Annual Premium ($)", min_value=0.0, value=1_000_000.0, step=10_000.0)
    elr = st.sidebar.number_input("Expected Loss Ratio", min_value=0.0, max_value=5.0, value=0.65, step=0.01)
    st.sidebar.caption(f"BF Expected Ultimate = ${elr * manual_premium:,.0f}")
else:
    st.sidebar.caption("BF Expected Ultimate = mean of CL ultimates.")

# ── Data Input ────────────────────────────────────────────────────────────────
st.header("Data Input")
tab_upload, tab_ref = st.tabs(["📁 Upload File", "📋 Column Reference"])

with tab_upload:
    fmt_choice = st.radio(
        "Input format",
        ["Individual claim records", "Pre-aggregated triangle (CAS / Schedule P)"],
        horizontal=True
    )
    is_preagg = fmt_choice.startswith("Pre")

    if is_preagg:
        st.markdown("Required: **AccidentYear**, **DevelopmentLag**, **CumPaidLoss** (or similar)")
    else:
        st.markdown("Required: **Accident_Year**, **Development_Lag**, **Amount**, **Settlement_Year**")

    uploaded = st.file_uploader("Upload data file", type=["xlsx", "xls", "csv"])

    if uploaded is not None:
        try:
            raw_df = pd.read_csv(uploaded) if uploaded.name.lower().endswith(".csv") else pd.read_excel(uploaded)
            raw_df = raw_df.dropna(how="all")

            # Company filter for pre-aggregated data
            if is_preagg:
                grp_col = None
                for c in raw_df.columns:
                    cl = c.lower().replace(" ", "_")
                    if any(k in cl for k in ["grname", "grp", "company", "group", "insurer", "carrier"]):
                        grp_col = c
                        break
                if grp_col and raw_df[grp_col].nunique() > 1:
                    companies = sorted(raw_df[grp_col].dropna().unique().tolist())
                    sel_co = st.selectbox("Select Company:", companies)
                    raw_df = raw_df[raw_df[grp_col] == sel_co].copy()
                    st.success(f"Filtered to: **{sel_co}**")

            st.subheader("Raw Data (first 10 rows)")
            st.dataframe(raw_df.head(10), use_container_width=True)

            # ── Column Mapping ───────────────────────────────────────────────
            col_map = {}
            if is_preagg:
                for c in raw_df.columns:
                    cl = c.lower().replace(" ", "_")
                    if "accident" in cl or cl in ("year", "ay"):
                        col_map.setdefault("Accident_Year", c)
                    if "developmentlag" in cl or "dev_lag" in cl or "lag" in cl:
                        col_map["Development_Lag"] = c          # Direct assign
                    if ("cum" in cl and "paid" in cl) or "cumpaid" in cl:
                        col_map["Amount"] = c                   # Prioritize CumPaid
                    elif "paid" in cl or "loss" in cl:
                        col_map.setdefault("Amount", c)
                    if "prem" in cl or "earned" in cl:
                        col_map.setdefault("Premium", c)
            else:
                for c in raw_df.columns:
                    cl = c.lower().replace(" ", "_")
                    if "accident" in cl or cl in ("year", "ay"):
                        col_map.setdefault("Accident_Year", c)
                    if "development" in cl or "lag" in cl:
                        col_map.setdefault("Development_Lag", c)
                    if "amount" in cl or "loss" in cl or ("paid" in cl and "latest" not in cl):
                        col_map.setdefault("Amount", c)
                    if "settlement" in cl:
                        col_map.setdefault("Settlement_Year", c)
                    if "premium" in cl or "prem" in cl:
                        col_map.setdefault("Premium", c)

            required = ["Accident_Year", "Development_Lag", "Amount"] if is_preagg else ["Accident_Year", "Development_Lag", "Amount", "Settlement_Year"]
            missing = [r for r in required if r not in col_map]

            if missing:
                st.error(f"Could not auto-detect columns: {missing}")
            else:
                work_df = raw_df.rename(columns={v: k for k, v in col_map.items()})
                for col in ["Accident_Year", "Development_Lag"]:
                    work_df[col] = pd.to_numeric(work_df[col], errors="coerce").astype("Int64")
                if not is_preagg:
                    work_df["Settlement_Year"] = pd.to_numeric(work_df["Settlement_Year"], errors="coerce").astype("Int64")
                work_df["Amount"] = pd.to_numeric(work_df["Amount"], errors="coerce").fillna(0)
                work_df = work_df.dropna(subset=required)

                st.session_state["work_df"] = work_df
                st.session_state["data_format"] = "pre_aggregated" if is_preagg else "individual"

                prem_series = None
                if "Premium" in work_df.columns:
                    prem_series = work_df.groupby("Accident_Year")["Premium"].first().astype(float)
                st.session_state["premium_series"] = prem_series

                st.success(f"✅ Data loaded! ({len(work_df):,} rows)")
        except Exception as e:
            st.error(f"Error: {e}")

# ── Column Reference ────────────────────────────────────────────────────────
with tab_ref:
    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("**Individual Claim Records**")
        st.markdown("""
        | Column            | Description |
        |-------------------|-------------|
        | `Accident_Year`   | Year the loss occurred |
        | `Development_Lag` | Development lag |
        | `Amount`          | Incremental claim payment |
        | `Settlement_Year` | Year the claim was paid |
        | `Premium`         | Optional earned premium |
        """)
    with col_r:
        st.markdown("**Pre-aggregated Triangle**")
        st.markdown("""
        | Column             | Description |
        |--------------------|-------------|
        | `AccidentYear`     | Accident year |
        | `DevelopmentLag`   | Development lag (0 or 1-indexed) |
        | `CumPaidLoss`      | **Cumulative** paid losses |
        | `EarnedPremNet`    | Optional earned premium |
        | `GRNAME`           | Company name (optional) |
        """)

# ── Run Model ───────────────────────────────────────────────────────────────
if st.button("🚀 RUN RESERVING MODEL", type="primary", use_container_width=True):
    if "work_df" not in st.session_state:
        st.error("No data loaded.")
        st.stop()

    df = st.session_state["work_df"].copy()
    premium_series = st.session_state.get("premium_series")
    data_format = st.session_state.get("data_format", "individual")
    vy = int(valuation_year)
    tail = float(tail_factor)

    if data_format == "individual":
        df = df[df["Settlement_Year"] <= vy].copy()
        if df.empty:
            st.error("No claims remain after filtering.")
            st.stop()
        for col in ["Accident_Year", "Development_Lag", "Settlement_Year"]:
            df[col] = df[col].astype(int)
        latest_paid = df.groupby("Accident_Year")["Amount"].sum()
        accident_years = sorted(int(ay) for ay in latest_paid.index)
        diag_lag = {ay: vy - ay for ay in accident_years}
        grouped = df.groupby(["Accident_Year", "Development_Lag"])["Amount"].sum().reset_index()
        tri_inc = grouped.pivot(index="Accident_Year", columns="Development_Lag", values="Amount").fillna(0)
        tri_inc.columns = [int(c) for c in tri_inc.columns]
        tri_inc = tri_inc.sort_index().sort_index(axis=1)
        tri_cum = tri_inc.cumsum(axis=1)
        lags = sorted(int(c) for c in tri_cum.columns)
    else:  # Pre-aggregated
        for col in ["Accident_Year", "Development_Lag"]:
            df[col] = df[col].astype(int)
        df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0)
        if df["Development_Lag"].min() == 1:
            df["Development_Lag"] = df["Development_Lag"] - 1
        df = df[df["Accident_Year"] + df["Development_Lag"] <= vy].copy()
        if df.empty:
            st.error("No data remains after filtering.")
            st.stop()
        accident_years = sorted(int(ay) for ay in df["Accident_Year"].unique())
        diag_lag = {ay: vy - ay for ay in accident_years}
        tri_cum = df.groupby(["Accident_Year", "Development_Lag"])["Amount"].sum().unstack().sort_index().sort_index(axis=1)
        tri_cum.columns = [int(c) for c in tri_cum.columns]
        lags = sorted(int(c) for c in tri_cum.columns)

        latest_paid_dict = {}
        for ay in accident_years:
            d = diag_lag[ay]
            if ay in tri_cum.index:
                row = tri_cum.loc[ay]
                valid_lags = row.index[row.index <= d]
                latest_paid_dict[ay] = float(row[valid_lags.max()]) if len(valid_lags) > 0 else 0.0
            else:
                latest_paid_dict[ay] = 0.0
        latest_paid = pd.Series(latest_paid_dict)

    # Common Logic
    ldfs = {}
    for i in range(len(lags)-1):
        c_lag, n_lag = lags[i], lags[i+1]
        eligible = [ay for ay in accident_years if diag_lag[ay] >= n_lag]
        key = f"{c_lag}-{n_lag}"
        if not eligible:
            ldfs[key] = 1.0
            continue
        sub = tri_cum.loc[eligible, [c_lag, n_lag]]
        mask = sub[c_lag].notna() & sub[n_lag].notna() & (sub[c_lag] > 0)
        ldfs[key] = sub.loc[mask, n_lag].sum() / sub.loc[mask, c_lag].sum() if mask.any() else 1.0

    ldf_vals = list(ldfs.values())
    cdfs = {}
    for si, lag in enumerate(lags):
        cdf = tail
        for j in range(si, len(ldf_vals)):
            cdf *= ldf_vals[j]
        cdfs[lag] = cdf

    def _cdf(d):
        return cdfs.get(d, tail)

    cl_ult, cl_res = {}, {}
    for ay in accident_years:
        lp = float(latest_paid[ay])
        u = lp * _cdf(diag_lag[ay])
        cl_ult[ay] = u
        cl_res[ay] = u - lp

    if premium_source == "Enter manually" and manual_premium and elr:
        def _eu(ay):
            if premium_series is not None and ay in premium_series.index:
                return elr * float(premium_series[ay])
            return elr * float(manual_premium)
        eu_display = elr * float(manual_premium)
    else:
        _mean = float(np.mean(list(cl_ult.values())))
        def _eu(_): return _mean
        eu_display = _mean

    bf_ult, bf_res = {}, {}
    for ay in accident_years:
        lp = float(latest_paid[ay])
        pct_dev = 1.0 / _cdf(diag_lag[ay])
        u = lp + _eu(ay) * (1 - pct_dev)
        bf_ult[ay] = u
        bf_res[ay] = u - lp

    # Build Results
    rows = []
    for ay in accident_years:
        rows.append({
            "Accident_Year": ay,
            "Latest_Paid": float(latest_paid[ay]),
            "Diagonal_Lag": diag_lag[ay],
            "CDF": _cdf(diag_lag[ay]),
            "Pct_Developed": 1.0 / _cdf(diag_lag[ay]),
            "CL_Ultimate": cl_ult[ay],
            "CL_Reserve": cl_res[ay],
            "BF_Ultimate": bf_ult[ay],
            "BF_Reserve": bf_res[ay],
            "Blend_50_50_Ult": (cl_ult[ay] + bf_ult[ay]) / 2,
            "Blend_50_50_Res": (cl_res[ay] + bf_res[ay]) / 2,
        })
    results = pd.DataFrame(rows).set_index("Accident_Year")

    # Build Triangles
    paid_data = {}
    for ay in accident_years:
        d = diag_lag[ay]
        row = {}
        for lag in lags:
            col_name = f"Lag {lag}"
            if lag <= d and ay in tri_cum.index:
                raw = tri_cum.at[ay, lag]
                row[col_name] = float(raw) if pd.notna(raw) else float("nan")
            else:
                row[col_name] = float("nan")
        paid_data[ay] = row
    paid_tri = pd.DataFrame.from_dict(paid_data, orient="index", dtype=float)
    paid_tri.index.name = "Accident_Year"

    res_data = {}
    for ay in accident_years:
        d = diag_lag[ay]
        u_cl = cl_ult[ay]
        row = {}
        for lag in lags:
            col_name = f"Lag {lag}"
            if lag <= d:
                paid = paid_data[ay][col_name]
                row[col_name] = u_cl - (0.0 if np.isnan(paid) else paid)
            else:
                row[col_name] = float("nan")
        row["CL_Reserve"] = cl_res[ay]
        res_data[ay] = row
    res_tri = pd.DataFrame.from_dict(res_data, orient="index", dtype=float)
    res_tri.index.name = "Accident_Year"

    max_lag = max(lags)
    fully_dev = [ay for ay in accident_years if diag_lag[ay] >= max_lag]
    most_immature = accident_years[-1]

    st.session_state["model_output"] = {
        "results": results, "res_tri": res_tri, "paid_tri": paid_tri,
        "ldfs": ldfs, "cdfs": cdfs, "eu_display": eu_display, "vy": vy,
        "fully_dev": fully_dev, "most_immature": most_immature,
        "accident_years": accident_years, "n_ays": len(accident_years),
        "max_lag": max_lag, "cl_res": cl_res, "bf_res": bf_res
    }

# ── OUTPUT ────────────────────────────────────────────────────────────────────
if "model_output" in st.session_state:
    o = st.session_state["model_output"]
    results = o["results"]
    res_tri = o["res_tri"]
    paid_tri = o["paid_tri"]
    ldfs = o["ldfs"]
    cdfs = o["cdfs"]
    eu_display = o["eu_display"]
    vy = o["vy"]
    fully_dev = o["fully_dev"]
    most_immature = o["most_immature"]
    accident_years = o["accident_years"]
    n_ays = o["n_ays"]
    max_lag = o["max_lag"]
    cl_res = o["cl_res"]
    bf_res = o["bf_res"]

    st.markdown("---")
    st.subheader("📐 Reserves Triangle (Chain-Ladder)")
    st.caption("Each cell = CL Ultimate − Cumulative Paid at that lag. — = future development.")
    tri_height = max(400, 30 + n_ays * 25)
    st.dataframe(res_tri.style.format("{:,.2f}", na_rep="—"), use_container_width=True, height=tri_height)

    if fully_dev:
        fd_str = " and ".join(str(ay) for ay in fully_dev)
        st.info(f"**AY {fd_str}** carry $0 CL Reserve (fully developed).")

    st.markdown("---")

    with st.expander("💰 Cumulative Paid Loss Triangle", expanded=False):
        st.dataframe(paid_tri.style.format("{:,.2f}", na_rep="—"), use_container_width=True)

    st.markdown("---")

    st.subheader("Summary")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Chain-Ladder Reserve", f"${results['CL_Reserve'].sum():,.0f}")
    c2.metric("BF Reserve", f"${results['BF_Reserve'].sum():,.0f}")
    c3.metric("50/50 Blend Reserve", f"${results['Blend_50_50_Res'].sum():,.0f}")
    c4.metric("BF Expected Ultimate", f"${eu_display:,.0f}")

    st.markdown("---")

    st.subheader("📊 Reserves by Accident Year")
    ays_str = [str(ay) for ay in accident_years]
    cl_vals = [cl_res[ay] for ay in accident_years]
    bf_vals = [bf_res[ay] for ay in accident_years]
    blend_vals = [(cl_res[ay] + bf_res[ay]) / 2 for ay in accident_years]

    fig = go.Figure()
    fig.add_trace(go.Bar(name="Chain-Ladder", x=ays_str, y=cl_vals, marker_color="#3B82F6"))
    fig.add_trace(go.Bar(name="Bornhuetter-Ferguson", x=ays_str, y=bf_vals, marker_color="#F59E0B"))
    fig.add_trace(go.Bar(name="50/50 Blend", x=ays_str, y=blend_vals, marker_color="#10B981"))
    fig.update_layout(barmode="group", xaxis_title="Accident Year", yaxis_title="Reserve ($)",
                      height=430, hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    st.subheader("Results by Accident Year")
    st.dataframe(results.style.format("{:,.2f}"), use_container_width=True)

    st.markdown("---")

    with st.expander("Development Factors", expanded=False):
        col_l, col_r = st.columns(2)
        with col_l:
            st.markdown("**Age-to-Age LDFs**")
            ldf_df = pd.DataFrame(list(ldfs.items()), columns=["Transition", "LDF"])
            st.dataframe(ldf_df.style.format({"LDF": "{:.6f}"}), use_container_width=True)
        with col_r:
            st.markdown("**CDFs to Ultimate**")
            cdf_df = pd.DataFrame(list(cdfs.items()), columns=["Lag", "CDF"]).sort_values("Lag")
            st.dataframe(cdf_df.style.format({"CDF": "{:.6f}"}), use_container_width=True)

    st.markdown("---")

    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        st.download_button("⬇ Download Results (CSV)", results.to_csv(), f"reserves_{vy}.csv", mime="text/csv")
    with col2:
        st.download_button("⬇ Download Reserves Triangle (CSV)", res_tri.to_csv(), f"reserves_triangle_{vy}.csv", mime="text/csv")
    with col3:
        if st.button("🔄 Reset All Data", type="secondary"):
            st.session_state.clear()
            st.rerun()