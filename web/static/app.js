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
  const m = Math.floor(ss / 60);
  const r = Math.floor(ss % 60);
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
  return { state: "", msg: healthObj.msg || "error" };
}

function toolStateText(on) { return on ? "ON" : "OFF"; }

function validationLine(name, v) {
  if (!v) return `${name}: --`;
  if (!v.on) return `${name}: OFF`;
  if (v.phase === "collecting")  return `${name}: COLLECT (${fmtSec(v.valid_in_s)} left)`;
  if (v.phase === "warmup")      return `${name}: WARMUP (${fmtSec(v.valid_in_s)} left)`;
  if (v.phase === "stabilizing") return `${name}: STABILIZE (${fmtSec(v.valid_in_s)} left)`;
  if (v.phase === "valid_window") return `${name}: VALID (${v.samples_left} left)`;
  return `${name}: DONE`;
}

async function refresh() {
  try {
    const res  = await fetch("/api/snapshot");
    const snap = await res.json();

    document.getElementById("uiState").textContent = "OK";

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
    setMsg("temp_msg",    H.temperature.msg);
    setMsg("gps_msg",     H.gps.msg);
    setMsg("imu_msg",     H.imu.msg);
    setMsg("soil_msg",    H.soil.msg);
    setMsg("ph_msg",      H.ph.msg);
    setMsg("air_msg",     H.air.msg);
    setMsg("mega_msg",    H.mega.msg);

    const data = snap.data || {};

    // ── Battery ──────────────────────────────────────────────────────────────
    const b        = data.battery     || {};
    const bPct     = safeNum(b.percentage);
    const bReserved  = b.reserved     || false;
    const bResPct  = safeNum(b.reserve_pct);

    const fillEl = document.getElementById("battery_fill");
    const pctEl  = document.getElementById("battery_pct");
    const rsvEl  = document.getElementById("battery_reserve");

    if (fillEl) {
      const w = bPct !== null ? Math.max(0, Math.min(100, bPct)) : 0;
      fillEl.style.width = w + "%";
      fillEl.style.background =
        bReserved    ? "var(--bad)"  :
        bPct < 20    ? "var(--bad)"  :
        bPct < 50    ? "var(--warn)" :
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

    // ── Temperature ───────────────────────────────────────────────────────────
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

    // ── IMU ───────────────────────────────────────────────────────────────────
    const imu = data.imu || {};
    const vel = imu.velocity || {};
    fillKV("imu_kv", [
      ["G-force", `${fmtNum(imu.g_force, 3)} g`],
      ["Vel X",   `${fmtNum(vel.x, 3)} m/s`],
      ["Vel Y",   `${fmtNum(vel.y, 3)} m/s`],
      ["Vel Z",   `${fmtNum(vel.z, 3)} m/s`],
    ]);

    // ── Soil Moisture (ADS1115 A0) ────────────────────────────────────────────
    const adc = data.adc || {};
    const raw = adc.raw             || {};
    const sv  = adc.sensor_voltage  || {};
    fillKV("soil_kv", [
      ["Moisture",  `${fmtNum(adc.moisture_value, 1)} %`],
      ["Raw",       fmtInt(raw.moisture)],
      ["Voltage",   `${fmtNum(sv.moisture, 3)} V`],
    ]);

    // ── pH Sensor (ADS1115 A1) ────────────────────────────────────────────────
    fillKV("ph_kv", [
      ["pH",     fmtNum(adc.ph_value, 2)],
      ["Raw",    fmtInt(raw.ph)],
      ["Voltage",`${fmtNum(sv.ph, 3)} V`],
    ]);

    // ── Air ───────────────────────────────────────────────────────────────────
    const air = data.air || {};
    fillKV("air_kv", [
      ["CO₂", `${fmtInt(air.co2_ppm)} ppm`],
    ]);

    // ── Mega + tools ──────────────────────────────────────────────────────────
    const mega  = data.mega  || {};
    const tools = mega.tools || {};
    fillKV("mega_kv", [
      ["Movement",   mega.movement   || "--"],
      ["AIR Tool",   toolStateText(tools.air)],
      ["WATER Tool", toolStateText(tools.water)],
      ["SOIL Tool",  toolStateText(tools.soil)],
    ]);

    // ── Validation ────────────────────────────────────────────────────────────
    const v    = snap.validation || {};
    fillKV("validation_kv", [
      ["AIR",   validationLine("AIR",   v.air   || null)],
      ["WATER", validationLine("WATER", v.water || null)],
      ["SOIL",  validationLine("SOIL",  v.soil  || null)],
    ]);

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