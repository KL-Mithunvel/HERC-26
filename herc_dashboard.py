"""
herc_dashboard.py — HERC-26 Post-Run Review Dashboard (Streamlit)
==================================================================
Run with:
    streamlit run herc_dashboard.py

Requirements: streamlit, pandas, plotly
"""

import sqlite3
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st
from pathlib import Path

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(layout="wide", page_title="HERC-26 Post-Run Review")
st.title("HERC-26 — Post-Run Review")

PROJECT_ROOT = Path(__file__).resolve().parent

# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.header("Settings")

_DB_OPTIONS = {
    "Pi / real hardware  (rover_logs.sqlite)": PROJECT_ROOT / "data" / "rover_logs.sqlite",
    "Sim / dev           (dev_logs.sqlite)":   PROJECT_ROOT / "data" / "dev_logs.sqlite",
}
_db_label = st.sidebar.selectbox("Database", list(_DB_OPTIONS.keys()))
DB_PATH   = _DB_OPTIONS[_db_label]

if not DB_PATH.exists():
    st.error(f"Database not found: `{DB_PATH}`")
    st.stop()

# ── Session selector ──────────────────────────────────────────────────────────
@st.cache_data(ttl=30)
def _load_sessions(db: str) -> pd.DataFrame:
    conn = sqlite3.connect(db)
    df = pd.read_sql_query(
        "SELECT session_id, started_utc, notes FROM sessions ORDER BY started_utc DESC", conn
    )
    conn.close()
    return df

sess_df = _load_sessions(str(DB_PATH))
if sess_df.empty:
    st.error("No sessions in database.")
    st.stop()

sess_labels = {
    f"{r.started_utc[:19]}  —  {r.notes or '(no notes)'}": r.session_id
    for _, r in sess_df.iterrows()
}
sel_label  = st.sidebar.selectbox("Session", list(sess_labels.keys()))
SESSION_ID = sess_labels[sel_label]

g_thresh = st.sidebar.slider("G-Force spike threshold (g)", 1.0, 5.0, 1.5, 0.1)

if st.sidebar.button("🔄  Refresh data"):
    st.cache_data.clear()
    st.rerun()

# ── Load telemetry ────────────────────────────────────────────────────────────
@st.cache_data(ttl=30)
def _load_telem(db: str, sid: str) -> pd.DataFrame:
    conn = sqlite3.connect(db)
    df = pd.read_sql_query(
        "SELECT * FROM telemetry WHERE session_id=? ORDER BY id ASC",
        conn, params=(sid,)
    )
    conn.close()
    df["ts_utc"] = pd.to_datetime(df["ts_utc"])
    return df

df = _load_telem(str(DB_PATH), SESSION_ID)
if df.empty:
    st.warning("No telemetry rows for this session.")
    st.stop()

# ── Helpers ───────────────────────────────────────────────────────────────────
def clean(s: pd.Series) -> pd.Series:
    """Replace -1 error sentinel with NaN so charts don't plot garbage."""
    s = pd.to_numeric(s, errors="coerce")   # handles int/float/NAType uniformly
    return s.where(s != -1)                 # -1 → NaN

def _last_valid(col: str):
    s = clean(df[col]).dropna()
    return float(s.iloc[-1]) if not s.empty else None

def _apply_dark(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        paper_bgcolor="#0b0f14",
        plot_bgcolor="#0b0f14",
        font_color="#e8eef6",
        legend=dict(bgcolor="rgba(0,0,0,0)", font_color="#e8eef6"),
    )
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.07)", showline=False, zeroline=False)
    fig.update_yaxes(gridcolor="rgba(255,255,255,0.07)", showline=False, zeroline=False)
    return fig

def _add_range_selector(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        xaxis=dict(
            rangeselector=dict(
                bgcolor="#1e2530",
                activecolor="#3b82f6",
                buttons=[
                    dict(count=1,  label="1m",  step="minute", stepmode="backward"),
                    dict(count=5,  label="5m",  step="minute", stepmode="backward"),
                    dict(count=10, label="10m", step="minute", stepmode="backward"),
                    dict(step="all", label="All"),
                ],
            ),
            rangeslider=dict(visible=True, bgcolor="#0b0f14"),
            type="date",
        )
    )
    return fig

def _valid_spans(col_valid: str):
    """Return list of (start_ts, end_ts) for contiguous blocks where col_valid == 1."""
    spans, in_span, t0, prev_t = [], False, None, None
    for _, row in df.iterrows():
        v = row.get(col_valid, 0)
        if v == 1 and not in_span:
            in_span, t0 = True, row["ts_utc"]
        elif v != 1 and in_span:
            spans.append((t0, prev_t))
            in_span = False
        prev_t = row["ts_utc"]
    if in_span and t0 is not None:
        spans.append((t0, prev_t))
    return spans

def _add_valid_band(fig: go.Figure, col_valid: str) -> go.Figure:
    for s, e in _valid_spans(col_valid):
        fig.add_vrect(x0=s, x1=e, fillcolor="rgba(34,197,94,0.15)",
                      layer="below", line_width=0)
    return fig

def _detect_runs(col_on: str, col_valid: str) -> list:
    """
    Find each contiguous ON period for a tool.
    Returns list of {start, end, had_valid, misfire}.
    A misfire = tool was activated but no valid sample was ever recorded.
    """
    runs, in_run, t0, had_v = [], False, None, False
    prev_t = None
    for _, row in df.iterrows():
        on = row.get(col_on, 0) == 1
        if on and not in_run:
            in_run, t0, had_v = True, row["ts_utc"], False
        if on and in_run and row.get(col_valid, 0) == 1:
            had_v = True
        if not on and in_run:
            runs.append(dict(start=t0, end=row["ts_utc"],
                             had_valid=had_v, misfire=not had_v))
            in_run = False
        prev_t = row["ts_utc"]
    if in_run:
        runs.append(dict(start=t0, end=df["ts_utc"].iloc[-1],
                         had_valid=had_v, misfire=not had_v))
    return runs

def _add_misfire_bands(fig: go.Figure, runs: list) -> go.Figure:
    for r in runs:
        if r["misfire"]:
            fig.add_vrect(
                x0=r["start"], x1=r["end"],
                fillcolor="rgba(239,68,68,0.10)", layer="below", line_width=0,
                annotation_text="misfire", annotation_position="top left",
                annotation_font_color="#ef4444", annotation_font_size=10,
            )
    return fig

# ── Pre-compute task runs ─────────────────────────────────────────────────────
air_runs   = _detect_runs("mega_air_on",   "air_valid")
water_runs = _detect_runs("mega_water_on", "water_valid")
soil_runs  = _detect_runs("mega_soil_on",  "soil_valid")

air_valid_rows   = df[df["air_valid"]   == 1]
water_valid_rows = df[df["water_valid"] == 1]
soil_valid_rows  = df[df["soil_valid"]  == 1]

# ── Session info strip ────────────────────────────────────────────────────────
dur = (df["ts_utc"].iloc[-1] - df["ts_utc"].iloc[0]).total_seconds()
m, s = divmod(int(dur), 60)
ic1, ic2, ic3, ic4 = st.columns(4)
ic1.metric("Run Duration",  f"{m}m {s:02d}s")
ic2.metric("Total Samples", f"{len(df):,}")
ic3.metric("Sample Rate",   f"{len(df) / max(dur, 1):.1f} Hz")
ic4.metric("Session start", sel_label[:19])

st.divider()

# ── Task Results ──────────────────────────────────────────────────────────────
st.subheader("Task Results")

def _task_card(col_ui, label, icon, valid_rows, val_col, unit, runs,
               warn_lo=None, warn_hi=None):
    with col_ui:
        val = clean(valid_rows[val_col]).mean() if not valid_rows.empty else None
        misfires  = sum(1 for r in runs if r["misfire"])
        good_runs = sum(1 for r in runs if not r["misfire"])

        if good_runs > 0:
            status_str = "✅ Valid reading recorded"
        elif runs:
            status_str = "🔴 Triggered but no valid reading"
        else:
            status_str = "⚪ Never activated"

        val_str = f"{val:.2f} {unit}" if val is not None else "—"
        st.markdown(f"#### {icon} {label}")
        st.metric("Measured value", val_str)
        st.caption(status_str)

        if misfires:
            st.warning(f"⚠️ {misfires} misfire(s) — tool activated but turned off early")
        if val is not None and warn_lo is not None and val < warn_lo:
            st.error(f"Value below expected range (< {warn_lo} {unit})")
        if val is not None and warn_hi is not None and val > warn_hi:
            st.error(f"Value above expected range (> {warn_hi} {unit})")

tc1, tc2, tc3 = st.columns(3)
_task_card(tc1, "Air — CO₂",      "💨", air_valid_rows,   "co2_ppm",          "ppm", air_runs)
_task_card(tc2, "Water — pH",      "💧", water_valid_rows, "water_ph",          "",    water_runs,
           warn_lo=4.0, warn_hi=10.0)
_task_card(tc3, "Soil — Moisture", "🌱", soil_valid_rows,  "soil_moisture_pct", "%",   soil_runs)

st.divider()

# ── End-of-run snapshot metrics ───────────────────────────────────────────────
st.subheader("End-of-Run Snapshot")

def _fmv(col, decimals=2):
    v = _last_valid(col)
    return round(v, decimals) if v is not None else "—"

def _maxv(col, decimals=3):
    s = clean(df[col]).dropna()
    return round(float(s.max()), decimals) if not s.empty else "—"

mc = st.columns(6)
mc[0].metric("Temp °C",     _fmv("temp_c", 2))
mc[1].metric("CO₂ ppm",     _fmv("co2_ppm", 0))
mc[2].metric("Soil %",      _fmv("soil_moisture_pct", 1))
mc[3].metric("pH",          _fmv("water_ph", 2))
mc[4].metric("Battery %",   _fmv("batt_percentage", 1))
mc[5].metric("Peak G-Force",_maxv("imu_g_force", 3))

st.divider()

# ── Battery ───────────────────────────────────────────────────────────────────
st.subheader("Battery")
fig_batt = go.Figure()
fig_batt.add_trace(go.Scatter(
    x=df["ts_utc"], y=clean(df["batt_percentage"]),
    mode="lines", name="Battery %", line=dict(color="#22c55e", width=2)
))
fig_batt.add_trace(go.Scatter(
    x=df["ts_utc"], y=clean(df["power_voltage_v"]),
    mode="lines", name="Voltage V", line=dict(color="#6ae4ff", width=1.5),
    yaxis="y2"
))
fig_batt.update_layout(
    title="Battery Over Run",
    yaxis=dict(title="Percentage %", range=[0, 105]),
    yaxis2=dict(title="Voltage V", overlaying="y", side="right"),
)
_apply_dark(fig_batt)
_add_range_selector(fig_batt)
st.plotly_chart(fig_batt, use_container_width=True)

# ── Temperature ───────────────────────────────────────────────────────────────
st.subheader("Temperature")
fig_temp = go.Figure()
fig_temp.add_trace(go.Scatter(
    x=df["ts_utc"], y=clean(df["temp_c"]),
    mode="lines", name="Temp °C", line=dict(color="#f59e0b", width=2)
))
fig_temp.update_layout(title="Temperature (°C)", yaxis_title="°C")
_apply_dark(fig_temp)
_add_range_selector(fig_temp)
st.plotly_chart(fig_temp, use_container_width=True)

# ── IMU ───────────────────────────────────────────────────────────────────────
st.subheader("IMU — G-Force")
fig_imu = go.Figure()

has_accel = "imu_accel_x" in df.columns
if has_accel:
    for col, color, lbl in [
        ("imu_accel_x", "#ef4444", "Accel X (g)"),
        ("imu_accel_y", "#22c55e", "Accel Y (g)"),
        ("imu_accel_z", "#6ae4ff", "Accel Z (g)"),
    ]:
        fig_imu.add_trace(go.Scatter(
            x=df["ts_utc"], y=clean(df[col]),
            mode="lines", name=lbl, line=dict(color=color, width=1.5)
        ))

# Scalar g_force + spike markers
gf = clean(df["imu_g_force"])
fig_imu.add_trace(go.Scatter(
    x=df["ts_utc"], y=gf,
    mode="lines", name="G-Force net",
    line=dict(color="white", width=1, dash="dot"), opacity=0.6
))
spikes = df[gf > g_thresh]
fig_imu.add_trace(go.Scatter(
    x=spikes["ts_utc"], y=gf[spikes.index],
    mode="markers", name=f"Spike > {g_thresh}g",
    marker=dict(color="orange", size=8, symbol="x")
))
fig_imu.update_layout(title="IMU G-Force (per axis + net)", yaxis_title="g")
_apply_dark(fig_imu)
_add_range_selector(fig_imu)
st.plotly_chart(fig_imu, use_container_width=True)

st.subheader("IMU — Velocity (integrated)")
fig_vel = go.Figure()
for col, color, lbl in [
    ("imu_vel_x", "#ef4444", "Vel X (m/s)"),
    ("imu_vel_y", "#22c55e", "Vel Y (m/s)"),
    ("imu_vel_z", "#6ae4ff", "Vel Z (m/s)"),
]:
    fig_vel.add_trace(go.Scatter(
        x=df["ts_utc"], y=clean(df[col]),
        mode="lines", name=lbl, line=dict(color=color, width=1.5)
    ))
fig_vel.update_layout(
    title="Velocity (integrated from linear accel — drift expected over long runs)",
    yaxis_title="m/s"
)
_apply_dark(fig_vel)
_add_range_selector(fig_vel)
st.plotly_chart(fig_vel, use_container_width=True)

st.divider()

# ── Task sensor charts ────────────────────────────────────────────────────────
st.subheader("CO₂ — Air Task")
fig_co2 = go.Figure()
fig_co2.add_trace(go.Scatter(
    x=df["ts_utc"], y=clean(df["co2_ppm"]),
    mode="lines", name="CO₂ ppm", line=dict(color="#6ae4ff", width=2)
))
_add_valid_band(fig_co2, "air_valid")
_add_misfire_bands(fig_co2, air_runs)
fig_co2.update_layout(
    title="CO₂ ppm  ·  green band = valid window  ·  red band = misfire",
    yaxis_title="ppm"
)
_apply_dark(fig_co2)
_add_range_selector(fig_co2)
st.plotly_chart(fig_co2, use_container_width=True)

st.subheader("pH — Water Task")
fig_ph = go.Figure()
fig_ph.add_trace(go.Scatter(
    x=df["ts_utc"], y=clean(df["water_ph"]),
    mode="lines", name="pH", line=dict(color="#38bdf8", width=2)
))
_add_valid_band(fig_ph, "water_valid")
_add_misfire_bands(fig_ph, water_runs)
fig_ph.update_layout(
    title="pH  ·  green band = valid window  ·  red band = misfire",
    yaxis_title="pH"
)
_apply_dark(fig_ph)
_add_range_selector(fig_ph)
st.plotly_chart(fig_ph, use_container_width=True)

st.subheader("Soil Moisture — Soil Task")
fig_soil = go.Figure()
fig_soil.add_trace(go.Scatter(
    x=df["ts_utc"], y=clean(df["soil_moisture_pct"]),
    mode="lines", name="Moisture %", line=dict(color="#a3e635", width=2)
))
_add_valid_band(fig_soil, "soil_valid")
_add_misfire_bands(fig_soil, soil_runs)
fig_soil.update_layout(
    title="Soil Moisture %  ·  green band = valid window  ·  red band = misfire",
    yaxis_title="%"
)
_apply_dark(fig_soil)
_add_range_selector(fig_soil)
st.plotly_chart(fig_soil, use_container_width=True)

# ── GPS map ───────────────────────────────────────────────────────────────────
st.divider()
st.subheader("GPS Rover Path")
gps_df = df.copy()
gps_df["gps_lat"] = clean(gps_df["gps_lat"])
gps_df["gps_lon"] = clean(gps_df["gps_lon"])
gps_df = gps_df.dropna(subset=["gps_lat", "gps_lon"])
if len(gps_df) > 0:
    fig_map = px.scatter_mapbox(
        gps_df, lat="gps_lat", lon="gps_lon",
        zoom=15, height=450, title="Rover GPS Path"
    )
    fig_map.update_layout(mapbox_style="open-street-map")
    st.plotly_chart(fig_map, use_container_width=True)
else:
    st.info("No valid GPS data in this session.")

# ── Tool activation log ───────────────────────────────────────────────────────
st.divider()
st.subheader("Tool Activation Log")

def _runs_to_table(runs: list, tool_name: str) -> list:
    rows = []
    for i, r in enumerate(runs, 1):
        dur_s = (r["end"] - r["start"]).total_seconds()
        rows.append({
            "Run":          i,
            "Tool":         tool_name,
            "Start":        str(r["start"])[:19],
            "End":          str(r["end"])[:19],
            "Duration (s)": round(dur_s, 1),
            "Valid":        "✅" if r["had_valid"] else "—",
            "Status":       "✅ Complete" if not r["misfire"] else "🔴 Misfire",
        })
    return rows

all_run_rows = (
    _runs_to_table(air_runs,   "AIR")
    + _runs_to_table(water_runs, "WATER")
    + _runs_to_table(soil_runs,  "SOIL")
)
if all_run_rows:
    st.dataframe(pd.DataFrame(all_run_rows), use_container_width=True)
else:
    st.info("No tool activations recorded in this session.")

# ── Raw telemetry ─────────────────────────────────────────────────────────────
st.divider()
with st.expander("Raw Telemetry (last 300 rows)"):
    st.dataframe(df.tail(300), use_container_width=True)