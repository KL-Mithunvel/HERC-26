import streamlit as st
import time
import math
import random
import pandas as pd
import serial
import json

st.set_page_config(layout="wide")

st.title("Rover Telemetry")

# ================= MODE =================

mode = st.sidebar.selectbox("Mode", ["DEV", "REAL"])

# ================= SERIAL INIT =================

@st.cache_resource
def init_serial():
    try:
        return serial.Serial("/dev/ttyACM0", 115200, timeout=1)
    except Exception as e:
        return None

ser = init_serial()

# ================= STATE =================

if "t0" not in st.session_state:
    st.session_state.t0 = time.time()

if "history" not in st.session_state:
    st.session_state.history = []

if "last_ok_time" not in st.session_state:
    st.session_state.last_ok_time = None

error_msg = None

# ================= DEV DATA =================

def get_dev_packet():
    t = time.time() - st.session_state.t0

    movement_states = ["STOP","FWD","BACK","LEFT","RIGHT"]
    move = movement_states[int((math.sin(t)+1)*2)]

    spL = int(200 * math.sin(t))
    spR = int(200 * math.cos(t))

    air = random.choice([0,1])
    water = random.choice([0,1])
    soil = random.choice([0,1])

    pump = water
    pumpT = round(max(0, 5 - (t % 5)),1)

    arm = 1 if (t % 10) < 5 else 0

    th1 = round((t*30) % 180,1)
    th2 = round((t*40) % 180,1)
    th3 = round((t*50) % 180,1)

    return {
        "move": move,
        "spL": spL,
        "spR": spR,
        "air": air,
        "water": water,
        "soil": soil,
        "pump": pump,
        "pumpT": pumpT,
        "arm": arm,
        "th1": th1,
        "th2": th2,
        "th3": th3,
        "ch1": 1500 + int(300*math.sin(t)),
        "ch2": 1500 + int(400*math.sin(t/2)),
        "ch3": 1500 + int(500*math.sin(t/3)),
    }

# ================= SERIAL SAFE READ =================

def read_serial_packet_safe():
    if ser is None:
        return None, "Serial port not available"

    try:
        line = ser.readline().decode(errors="ignore").strip()

        if not line:
            return None, "No data received"

        if not line.startswith("{"):
            return None, "Invalid data format"

        data = json.loads(line)
        return data, None

    except json.JSONDecodeError:
        return None, "JSON parse error"

    except Exception as e:
        return None, f"Serial error: {str(e)}"

# ================= PACKET SOURCE =================

def get_packet():
    global error_msg

    if mode == "DEV":
        return get_dev_packet()
    else:
        packet, err = read_serial_packet_safe()
        error_msg = err
        return packet

packet = get_packet()

# ================= HISTORY =================

if packet:
    st.session_state.history.append(packet)
    st.session_state.last_ok_time = time.time()

if len(st.session_state.history) > 150:
    st.session_state.history.pop(0)

df = pd.DataFrame(st.session_state.history)

# ================= SIDEBAR =================

st.sidebar.subheader("Control")

if st.sidebar.button("Kill Rover"):
    if mode == "REAL" and ser:
        ser.write(b'3')
    else:
        st.sidebar.write("Kill command simulated")

st.sidebar.subheader("Status")
st.sidebar.write(f"Mode: {mode}")

# ================= SYSTEM STATUS =================

st.subheader("System Status")

col_s1, col_s2 = st.columns(2)

if mode == "REAL":
    if error_msg:
        col_s1.error("Connection Issue")
        col_s2.write(error_msg)
    else:
        col_s1.success("Connected")
        col_s2.write("Receiving data")
else:
    col_s1.info("DEV Mode")
    col_s2.write("Simulated data")

if st.session_state.last_ok_time:
    st.write(f"Last data: {round(time.time() - st.session_state.last_ok_time,1)} s ago")

# ================= UI =================

if packet:

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Movement", packet["move"])
    col2.metric("Speed L", packet["spL"])
    col3.metric("Speed R", packet["spR"])
    col4.metric("Pump Time", packet["pumpT"])

    st.subheader("Tools")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Air", packet["air"])
    c2.metric("Water", packet["water"])
    c3.metric("Soil", packet["soil"])
    c4.metric("Pump", packet["pump"])

    st.subheader("Soil Arm")

    a, b, c = st.columns(3)

    a.progress(packet["th1"]/180)
    a.caption(f"Theta1: {packet['th1']}")

    b.progress(packet["th2"]/180)
    b.caption(f"Theta2: {packet['th2']}")

    c.progress(packet["th3"]/180)
    c.caption(f"Theta3: {packet['th3']}")

    st.subheader("Drive Speeds")
    if not df.empty:
        st.line_chart(df[["spL","spR"]])

    st.subheader("RC Channels")
    if not df.empty:
        st.line_chart(df[["ch1","ch2","ch3"]])

    with st.expander("Raw Data"):
        st.json(packet)

else:
    st.warning("Waiting for data...")
    if mode == "REAL" and error_msg:
        st.error(error_msg)

# ================= REFRESH =================

time.sleep(0.05)
st.rerun()
