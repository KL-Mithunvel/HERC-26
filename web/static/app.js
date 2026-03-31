// ── IMU rolling buffer & Chart.js setup ──────────────────────────────────────
const GRAPH_N = 60;  // 60 samples × 500 ms = 30-second rolling window

const _imuBuf = {
  ax: Array(GRAPH_N).fill(null), ay: Array(GRAPH_N).fill(null), az: Array(GRAPH_N).fill(null),
  vx: Array(GRAPH_N).fill(null), vy: Array(GRAPH_N).fill(null), vz: Array(GRAPH_N).fill(null),
};
const _chartLabels = Array(GRAPH_N).fill("");

function _ds(label, buf, color) {
  return {
    label,
    data: buf,
    borderColor: color,
    backgroundColor: "transparent",
    tension: 0.3,
    pointRadius: 0,
    borderWidth: 1.5,
  };
}

function _chartOpts(yUnit) {
  return {
    animation: false,
    responsive: true,
    maintainAspectRatio: false,
    scales: {
      x: { display: false },
      y: {
        title: { display: true, text: yUnit, color: "rgba(232,238,246,0.40)", font: { size: 10 } },
        ticks: { color: "rgba(232,238,246,0.55)", font: { size: 10 }, maxTicksLimit: 5 },
        grid:  { color: "rgba(255,255,255,0.06)" },
      },
    },
    plugins: {
      legend: {
        labels: { color: "rgba(232,238,246,0.65)", font: { size: 10 }, boxWidth: 16, padding: 10 },
      },
      tooltip: { enabled: false },
    },
  };
}

const gforceChart = new Chart(document.getElementById("chart_gforce"), {
  type: "line",
  data: {
    labels: _chartLabels,
    datasets: [
      _ds("X (g)", _imuBuf.ax, "#ef4444"),
      _ds("Y (g)", _imuBuf.ay, "#22c55e"),
      _ds("Z (g)", _imuBuf.az, "#6ae4ff"),
    ],
  },
  options: _chartOpts("g"),
});

const velChart = new Chart(document.getElementById("chart_velocity"), {
  type: "line",
  data: {
    labels: _chartLabels,
    datasets: [
      _ds("X (m/s)", _imuBuf.vx, "#ef4444"),
      _ds("Y (m/s)", _imuBuf.vy, "#22c55e"),
      _ds("Z (m/s)", _imuBuf.vz, "#6ae4ff"),
    ],
  },
  options: _chartOpts("m/s"),
});

function _pushImu(ag, vel) {
  _imuBuf.ax.shift(); _imuBuf.ax.push(ag?.x  ?? null);
  _imuBuf.ay.shift(); _imuBuf.ay.push(ag?.y  ?? null);
  _imuBuf.az.shift(); _imuBuf.az.push(ag?.z  ?? null);
  _imuBuf.vx.shift(); _imuBuf.vx.push(vel?.x ?? null);
  _imuBuf.vy.shift(); _imuBuf.vy.push(vel?.y ?? null);
  _imuBuf.vz.shift(); _imuBuf.vz.push(vel?.z ?? null);
  gforceChart.update("none");
  velChart.update("none");
}

// ── Utility helpers ───────────────────────────────────────────────────────────
async function post(url) {
  const res = await fetch(url, { method: "POST" });
  return res.json();
}

function setLED(id, state) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove("good", "warn");
  if (state === "good") el.classList.add("good");
  else if (state === "warn") el.classList.add("warn");
}

function safeNum(x) {
  if (x === null || x === undefined) return null;
  const n = Number(x);
  return Number.isFinite(n) ? n : null;
}

function fmtNum(x, digits = 2) {
  const n = safeNum(x);
  if (n === null) return "--";
  return n.toFixed(digits);
}

function fmtInt(x) {
  const n = safeNum(x);
  if (n === null) return "--";
  return String(Math.round(n));
}

function fmtSec(s) {
  const n = safeNum(s);
  if (n === null) return "--";
  const ss = Math.max(0, n);
  const m  = Math.floor(ss / 60);
  const r  = Math.floor(ss % 60);
  return `${m}:${String(r).padStart(2, "0")}`;
}

function fillKV(containerId, rows) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = "";
  for (const [k, v] of rows) {
    const kDiv = document.createElement("div");
    kDiv.className = "k";
    kDiv.textContent = k;
    const vDiv = document.createElement("div");
    vDiv.className = "v";
    vDiv.textContent = v;
    el.appendChild(kDiv);
    el.appendChild(vDiv);
  }
}

function setMsg(id, msg) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg ? String(msg) : "";
}

function healthToLed(healthObj) {
  if (!healthObj) return { state: "warn", msg: "no health" };
  if (healthObj.ok === true) return { state: "good", msg: "" };
  if (healthObj.reconnecting === true) return { state: "warn", msg: "reconnecting..." };
  return { state: "", msg: healthObj.msg || "error" };
}

function toolStateText(on) { return on ? "ON" : "OFF"; }

// Used by the Validation card (shows full label + phase)
function validationLine(name, v) {
  if (!v) return `${name}: --`;
  if (!v.on) return `${name}: OFF`;
  if (v.phase === "waiting")      return `${name}: WAITING (${fmtSec(v.valid_in_s)} left)`;
  if (v.phase === "stabilizing")  return `${name}: STABILIZE (${fmtSec(v.valid_in_s)} left)`;
  if (v.phase === "valid_window") return `${name}: VALID (${v.samples_left} left)`;
  return `${name}: DONE`;
}

// Used by task tool cards (compact phase line, no label prefix)
function validationPhase(v) {
  if (!v || !v.on) return "";
  if (v.phase === "waiting")      return `WAITING  \u2014  ${fmtSec(v.valid_in_s)} left`;
  if (v.phase === "stabilizing")  return `STABILIZE  \u2014  ${fmtSec(v.valid_in_s)} left`;
  if (v.phase === "valid_window") return `\u2713 VALID  \u2014  ${v.samples_left} samples left`;
  return "\u2713 DONE";
}

// ── Stale-data detection ──────────────────────────────────────────────────────
// If snap.ts hasn't advanced across 3 consecutive polls (≈1.5 s) the backend
// loop has stopped calling set_latest(). Show a visible warning.
let _lastTs     = 0;
let _staleCount = 0;

// ── Main refresh loop ─────────────────────────────────────────────────────────
async function refresh() {
  try {
    const res  = await fetch("/api/snapshot");
    const snap = await res.json();

    if (snap.ts === _lastTs) {
      _staleCount++;
    } else {
      _lastTs     = snap.ts;
      _staleCount = 0;
    }

    const stale = _staleCount >= 3;
    const uiEl  = document.getElementById("uiState");
    if (uiEl) {
      uiEl.textContent  = stale ? "STALE DATA" : "OK";
      uiEl.style.color  = stale ? "var(--warn)" : "";
    }

    const errCount = Object.keys(snap.errors || {}).length;
    document.getElementById("meta").textContent =
      `ts=${fmtNum(snap.ts, 2)} | errors=${errCount}`;

    document.getElementById("runState").textContent = snap.run_enabled ? "ON" : "OFF";

    const health = snap.health || {};
    const H = {
      battery:     healthToLed(health.battery),
      temperature: healthToLed(health.temperature),
      gps:         healthToLed(health.gps),
      imu:         healthToLed(health.imu),
      soil:        healthToLed(health.soil),
      ph:          healthToLed(health.ph),
      air:         healthToLed(health.air),
      mega:        healthToLed(health.mega),
    };

    setLED("led_battery",     H.battery.state);
    setLED("led_temperature", H.temperature.state);
    setLED("led_gps",         H.gps.state);
    setLED("led_imu",         H.imu.state);
    setLED("led_soil",        H.soil.state);
    setLED("led_ph",          H.ph.state);
    setLED("led_air",         H.air.state);
    setLED("led_mega",        H.mega.state);

    setMsg("battery_msg", H.battery.msg);
    setMsg("imu_msg",     H.imu.msg);
    setMsg("gps_msg",     H.gps.msg);
    setMsg("air_msg",     H.air.msg);
    setMsg("ph_msg",      H.ph.msg);
    setMsg("soil_msg",    H.soil.msg);
    setMsg("mega_msg",    H.mega.msg);

    const data  = snap.data || {};
    const mega  = data.mega  || {};
    const tools = mega.tools || {};
    const v     = snap.validation || {};

    // ── Battery ──────────────────────────────────────────────────────────────
    const b         = data.battery || {};
    const bPct      = safeNum(b.percentage);
    const bReserved = b.reserved   || false;
    const bResPct   = safeNum(b.reserve_pct);

    const fillEl = document.getElementById("battery_fill");
    const pctEl  = document.getElementById("battery_pct");
    const rsvEl  = document.getElementById("battery_reserve");

    if (fillEl) {
      const w = bPct !== null ? Math.max(0, Math.min(100, bPct)) : 0;
      fillEl.style.width = w + "%";
      fillEl.style.background =
        bReserved  ? "var(--bad)"  :
        bPct < 20  ? "var(--bad)"  :
        bPct < 50  ? "var(--warn)" :
                     "var(--good)";
    }
    if (pctEl) pctEl.textContent = bPct !== null ? fmtNum(bPct, 1) + "%" : "--%";
    if (rsvEl) rsvEl.textContent = bReserved
      ? "RESERVE" + (bResPct !== null ? "  " + fmtNum(bResPct, 1) + "% left" : "")
      : "";

    fillKV("battery_kv", [
      ["Voltage", `${fmtNum(b.voltage_v, 2)} V`],
      ["Reserve", bReserved ? `${fmtNum(bResPct, 1)} %` : "—"],
    ]);

    // ── Temperature ──────────────────────────────────────────────────────────
    const t = data.temperature || {};
    fillKV("temp_kv", [
      ["Temp", `${fmtNum(t.temp_c, 2)} °C`],
    ]);

    // ── GPS ───────────────────────────────────────────────────────────────────
    const g = data.gps || {};
    fillKV("gps_kv", [
      ["UTC TS", fmtInt(g.timestamp)],
      ["Lat",    fmtNum(g.lat, 6)],
      ["Lon",    fmtNum(g.lon, 6)],
    ]);

    // ── IMU — current values + push to graphs ─────────────────────────────────
    const imu = data.imu || {};
    const ag  = imu.accel_g  || {};
    const vel = imu.velocity || {};
    fillKV("imu_kv", [
      ["G-Force",  `${fmtNum(imu.g_force, 3)} g`],
      ["Accel X",  `${fmtNum(ag.x,  3)} g`],
      ["Accel Y",  `${fmtNum(ag.y,  3)} g`],
      ["Accel Z",  `${fmtNum(ag.z,  3)} g`],
      ["Vel X",    `${fmtNum(vel.x, 3)} m/s`],
      ["Vel Y",    `${fmtNum(vel.y, 3)} m/s`],
      ["Vel Z",    `${fmtNum(vel.z, 3)} m/s`],
    ]);
    _pushImu(ag, vel);

    // ── Mega — movement & RC status ───────────────────────────────────────────
    fillKV("mega_kv", [
      ["Movement",  mega.movement     || "--"],
      ["RC Signal", mega.ibus_pulse   ? "OK"      : "LOST"],
      ["Pump",      mega.pump_running ? "RUNNING" : "OFF"],
      ["Failsafe",  mega.failsafe     ? "ACTIVE"  : "OK"],
    ]);

    // ── Validation card (summary of all 3 tools) ──────────────────────────────
    fillKV("validation_kv", [
      ["AIR",   validationLine("AIR",   v.air   || null)],
      ["WATER", validationLine("WATER", v.water || null)],
      ["SOIL",  validationLine("SOIL",  v.soil  || null)],
    ]);

    // ── Air Task card
    // Left LED  (led_air)      = CO₂ sensor health
    // Right LED (led_air_task) = tool activated by Mega
    const air  = data.air || {};
    setLED("led_air_task", tools.air ? "good" : "");
    setMsg("air_task_state", toolStateText(tools.air));
    fillKV("air_kv", [
      ["CO₂", `${fmtInt(air.co2_ppm)} ppm`],
    ]);
    setMsg("air_phase", validationPhase(v.air || null));

    // ── Water Task card
    // Left LED  (led_ph)         = pH sensor health
    // Right LED (led_water_task) = tool activated by Mega
    const adc = data.adc || {};
    const sv  = adc.sensor_voltage || {};
    setLED("led_water_task", tools.water ? "good" : "");
    setMsg("water_task_state", toolStateText(tools.water));
    fillKV("ph_kv", [
      ["pH",      fmtNum(adc.ph_value, 2)],
      ["Voltage", `${fmtNum(sv.ph,     3)} V`],
    ]);
    setMsg("water_phase", validationPhase(v.water || null));

    // ── Soil Task card
    // Left LED  (led_soil)       = soil moisture sensor health
    // Right LED (led_soil_task)  = tool activated by Mega
    setLED("led_soil_task", tools.soil ? "good" : "");
    setMsg("soil_task_state", toolStateText(tools.soil));
    fillKV("soil_kv", [
      ["Moisture", `${fmtNum(adc.moisture_value, 1)} %`],
      ["Voltage",  `${fmtNum(sv.moisture,        3)} V`],
    ]);
    setMsg("soil_phase", validationPhase(v.soil || null));

    // ── Status log ────────────────────────────────────────────────────────────
    const log   = snap.status_log || [];
    const lines = log.map(x => {
      const ts = new Date((x.ts || 0) * 1000).toLocaleTimeString();
      return `[${ts}] ${x.msg}`;
    });
    document.getElementById("status_box").value = lines.join("\n");

  } catch (e) {
    document.getElementById("uiState").textContent = "DISCONNECTED";
  }
}

document.getElementById("runOn").addEventListener("click",  async () => { await post("/api/run/on");  });
document.getElementById("runOff").addEventListener("click", async () => { await post("/api/run/off"); });

setInterval(refresh, 500);
refresh();
