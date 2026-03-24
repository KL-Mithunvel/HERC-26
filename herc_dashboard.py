''' Note for Mithun or anyone else running it; install the below requirements to your venv if you haven't already.
 The requirements has also been updated
 If you find any issues text Krishna '''


import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path

# CONFIG
PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "data" / "rover_logs.sqlite"

st.set_page_config(layout="wide", page_title="HERC Rover Telemetry")
st.title("HERC Rover Telemetry Dashboard")

# LOAD DATA
@st.cache_data
def load_data():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM telemetry ORDER BY id ASC", conn)
    conn.close()
    df["ts_utc"] = pd.to_datetime(df["ts_utc"])
    return df

if not DB_PATH.exists():
    st.error(f"Database not found at {DB_PATH}")
    st.stop()

df = load_data()

# TOOL ACTIVATION DETECTION
df["air_tool_event"] = df["mega_air_on"].diff() == 1
df["soil_tool_event"] = df["mega_soil_on"].diff() == 1
df["water_tool_event"] = df["mega_water_on"].diff() == 1

air_events = df[df["air_tool_event"]]
soil_events = df[df["soil_tool_event"]]
water_events = df[df["water_tool_event"]]

# SIDEBAR
st.sidebar.header("Filters")
sample_range = st.sidebar.slider(
    "Samples to display",
    min_value=len(df.head()),
    max_value=len(df),
    value=min(2000, len(df))
)

df = df.tail(sample_range)

# CURRENT SNAPSHOT
st.subheader("Current Telemetry Snapshot")
latest = df.iloc[-1]

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Temp °C", round(latest["temp_c"], 2))
c2.metric("CO₂ ppm", latest["co2_ppm"])
c3.metric("Soil %", round(latest["soil_moisture_pct"], 2))
c4.metric("Water pH", round(latest["water_ph"], 2))
c5.metric("Voltage V", round(latest["power_voltage_v"], 2))
c6.metric("G Force", round(latest["imu_g_force"], 3))

# RANGE SELECTOR
def add_range_selector(fig):
    fig.update_layout(
        xaxis=dict(
            rangeselector=dict(
                buttons=[
                    dict(count=1,label="1m",step="minute",stepmode="backward"),
                    dict(count=5,label="5m",step="minute",stepmode="backward"),
                    dict(count=10,label="10m",step="minute",stepmode="backward"),
                    dict(count=1,label="1h",step="hour",stepmode="backward"),
                    dict(step="all")
                ]
            ),
            rangeslider=dict(visible=True),
            type="date"
        )
    )
    return fig

# TEMPERATURE
st.subheader("Temperature")

fig_temp = px.line(df,x="ts_utc",y="temp_c",title="Temperature (°C)")

fig_temp.add_trace(go.Scatter(
    x=air_events["ts_utc"],
    y=air_events["temp_c"],
    mode="markers",
    marker=dict(color="red",size=8),
    name="Air Tool Activated"
))

fig_temp.add_trace(go.Scatter(
    x=soil_events["ts_utc"],
    y=soil_events["temp_c"],
    mode="markers",
    marker=dict(color="green",size=8),
    name="Soil Tool Activated"
))

fig_temp.add_trace(go.Scatter(
    x=water_events["ts_utc"],
    y=water_events["temp_c"],
    mode="markers",
    marker=dict(color="blue",size=8),
    name="Water Tool Activated"
))

fig_temp = add_range_selector(fig_temp)
st.plotly_chart(fig_temp,use_container_width=True)

# CO2
st.subheader("CO₂ Levels")

fig_co2 = px.line(df,x="ts_utc",y="co2_ppm",title="CO₂ ppm")

fig_co2.add_trace(go.Scatter(
    x=air_events["ts_utc"],
    y=air_events["co2_ppm"],
    mode="markers",
    marker=dict(color="red",size=8),
    name="Air Tool Activated"
))

fig_co2 = add_range_selector(fig_co2)
st.plotly_chart(fig_co2,use_container_width=True)

# SOIL
st.subheader("Soil Moisture")

fig_soil = px.line(df,x="ts_utc",y="soil_moisture_pct",title="Soil Moisture %")

fig_soil.add_trace(go.Scatter(
    x=soil_events["ts_utc"],
    y=soil_events["soil_moisture_pct"],
    mode="markers",
    marker=dict(color="green",size=8),
    name="Soil Tool Activated"
))

fig_soil = add_range_selector(fig_soil)
st.plotly_chart(fig_soil,use_container_width=True)

# WATER PH
st.subheader("Water pH")

fig_ph = px.line(df,x="ts_utc",y="water_ph",title="Water pH")

fig_ph.add_trace(go.Scatter(
    x=water_events["ts_utc"],
    y=water_events["water_ph"],
    mode="markers",
    marker=dict(color="blue",size=8),
    name="Water Tool Activated"
))

fig_ph = add_range_selector(fig_ph)
st.plotly_chart(fig_ph,use_container_width=True)

# IMU ORIENTATION
st.subheader("IMU Orientation")

fig_imu = go.Figure()

fig_imu.add_trace(go.Scatter(x=df["ts_utc"],y=df["imu_roll_deg"],mode="lines",name="Roll"))
fig_imu.add_trace(go.Scatter(x=df["ts_utc"],y=df["imu_pitch_deg"],mode="lines",name="Pitch"))
fig_imu.add_trace(go.Scatter(x=df["ts_utc"],y=df["imu_yaw_deg"],mode="lines",name="Yaw"))

fig_imu.update_layout(title="IMU Orientation")
fig_imu = add_range_selector(fig_imu)

st.plotly_chart(fig_imu,use_container_width=True)

# G FORCE
st.subheader("G Force Monitoring")

g_threshold = 1.2
spikes = df[df["imu_g_force"] > g_threshold]

fig_g = go.Figure()

fig_g.add_trace(go.Scatter(
    x=df["ts_utc"],
    y=df["imu_g_force"],
    mode="lines",
    name="G Force"
))

fig_g.add_trace(go.Scatter(
    x=spikes["ts_utc"],
    y=spikes["imu_g_force"],
    mode="markers",
    marker=dict(color="red",size=10),
    name="Spike Detected"
))

fig_g.update_layout(title="IMU G Force")
fig_g = add_range_selector(fig_g)

st.plotly_chart(fig_g,use_container_width=True)

# GPS MAP
st.subheader("GPS Rover Path")

gps_df = df[(df["gps_lat"] != -1) & (df["gps_lon"] != -1)]

if len(gps_df) > 0:
    fig_map = px.scatter_mapbox(
        gps_df,
        lat="gps_lat",
        lon="gps_lon",
        zoom=15,
        height=500,
        title="Rover GPS Path"
    )
    fig_map.update_layout(mapbox_style="open-street-map")
    st.plotly_chart(fig_map,use_container_width=True)
else:
    st.warning("No GPS data available")

# TOOL ACTIVATION LOG
st.subheader("Tool Activation Events")

events = pd.concat([
    air_events.assign(tool="AIR"),
    soil_events.assign(tool="SOIL"),
    water_events.assign(tool="WATER")
])

events = events[["ts_utc","tool"]].sort_values("ts_utc")

st.dataframe(events)

# SENSOR DISTRIBUTION
st.subheader("Sensor Distribution")

fig_box = go.Figure()

fig_box.add_trace(go.Box(y=df["temp_c"],name="Temp"))
fig_box.add_trace(go.Box(y=df["co2_ppm"],name="CO2"))
fig_box.add_trace(go.Box(y=df["soil_moisture_pct"],name="Soil"))
fig_box.add_trace(go.Box(y=df["water_ph"],name="pH"))

fig_box.update_layout(title="Sensor Stability")

st.plotly_chart(fig_box,use_container_width=True)

# RAW TELEMETRY TABLE
st.subheader("Telemetry Logs")

st.dataframe(df.tail(300),use_container_width=True)