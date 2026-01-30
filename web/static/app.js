async function post(url) {
  const res = await fetch(url, { method: "POST" });
  return res.json();
}

function setLED(id, state) {
  const el = document.getElementById(id);
  if (!el) return;

  el.classList.remove("good", "warn");
  // default is red (bad)

  if (state === "good") el.classList.add("good");
  else if (state === "warn") el.classList.add("warn");
}

function safeNum(x) {
  if (x === null || x === undefined) return null;
  const n = Number(x);
  return Number.isFinite(n) ? n : null;
}

function fmtNum(x, digits=2) {
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
  // rows: array of [label, value]
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
  if (!healthObj) return {state:"warn", msg:"no health"};
  if (healthObj.ok === true) return {state:"good", msg:""};
  // error message -> red
  return {state:"", msg: healthObj.msg || "error"};
}

function toolStateText(on) { return on ? "ON" : "OFF"; }

function validationLine(name, v) {
  if (!v) return `${name}: --`;
  if (!v.on) return `${name}: OFF`;

  if (v.phase === "collecting") return `${name}: COLLECT (${fmtSec(v.valid_in_s)} left)`;
  if (v.phase === "warmup") return `${name}: WARMUP (${fmtSec(v.valid_in_s)} left)`;
  if (v.phase === "stabilizing") return `${name}: STABILIZE (${fmtSec(v.valid_in_s)} left)`;
  if (v.phase === "valid_window") return `${name}: VALID (${v.samples_left} left)`;
  return `${name}: DONE`;
}

async function refresh() {
  try {
    const res = await fetch("/api/snapshot");
    const snap = await res.json();

    document.getElementById("uiState").textContent = "OK";

    const errCount = Object.keys(snap.errors || {}).length;
    document.getElementById("meta").textContent =
      `ts=${fmtNum(snap.ts, 2)} | errors=${errCount}`;

    document.getElementById("runState").textContent = snap.run_enabled ? "ON" : "OFF";

    const health = snap.health || {};
    // LEDs + messages
    const H = {
      power: healthToLed(health.power),
      temperature: healthToLed(health.temperature),
      gps: healthToLed(health.gps),
      imu: healthToLed(health.imu),
      adc: healthToLed(health.adc),
      air: healthToLed(health.air),
      mega: healthToLed(health.mega),
    };

    setLED("led_power", H.power.state);
    setLED("led_temperature", H.temperature.state);
    setLED("led_gps", H.gps.state);
    setLED("led_imu", H.imu.state);
    setLED("led_adc", H.adc.state);
    setLED("led_air", H.air.state);
    setLED("led_mega", H.mega.state);

    setMsg("power_msg", H.power.msg);
    setMsg("temp_msg", H.temperature.msg);
    setMsg("gps_msg", H.gps.msg);
    setMsg("imu_msg", H.imu.msg);
    setMsg("adc_msg", H.adc.msg);
    setMsg("air_msg", H.air.msg);
    setMsg("mega_msg", H.mega.msg);

    const data = snap.data || {};

    // Power
    const p = data.power || {};
    fillKV("power_kv", [
      ["Voltage", `${fmtNum(p.voltage_v, 2)} V`],
      ["Current", `${fmtNum(p.current_a, 2)} A`],
      ["Power",   `${fmtNum(p.power_w, 2)} W`],
    ]);

    // Temperature
    const t = data.temperature || {};
    fillKV("temp_kv", [
      ["Temp", `${fmtNum(t.temp_c, 2)} °C`],
    ]);

    // GPS
    const g = data.gps || {};
    fillKV("gps_kv", [
      ["UTC TS", `${fmtInt(g.timestamp)}`],
      ["Lat", `${fmtNum(g.lat, 6)}`],
      ["Lon", `${fmtNum(g.lon, 6)}`],
    ]);

    // IMU
    const imu = data.imu || {};
    const acc = imu.acceleration || {};
    const ori = imu.orientation || {};
    const vel = imu.velocity || {};
    fillKV("imu_kv", [
      ["Acc X", `${fmtNum(acc.x, 3)} m/s²`],
      ["Acc Y", `${fmtNum(acc.y, 3)} m/s²`],
      ["Acc Z", `${fmtNum(acc.z, 3)} m/s²`],
      ["Roll", `${fmtNum(ori.roll, 2)} °`],
      ["Pitch", `${fmtNum(ori.pitch, 2)} °`],
      ["Yaw", `${fmtNum(ori.yaw, 2)} °`],
      ["G-force", `${fmtNum(imu.g_force, 3)} g`],
      ["Vel X", `${fmtNum(vel.x, 3)} m/s`],
      ["Vel Y", `${fmtNum(vel.y, 3)} m/s`],
      ["Vel Z", `${fmtNum(vel.z, 3)} m/s`],
    ]);

    // ADC
    const adc = data.adc || {};
    const raw = adc.raw || {};
    const sv = adc.sensor_voltage || {};
    fillKV("adc_kv", [
      ["pH", `${fmtNum(adc.ph_value, 2)}`],
      ["Moisture", `${fmtNum(adc.moisture_value, 1)} %`],
      ["Raw pH", `${fmtInt(raw.ph)}`],
      ["Raw Moist", `${fmtInt(raw.moisture)}`],
      ["pH V", `${fmtNum(sv.ph, 3)} V`],
      ["Moist V", `${fmtNum(sv.moisture, 3)} V`],
    ]);

    // Air
    const air = data.air || {};
    fillKV("air_kv", [
      ["CO₂", `${fmtInt(air.co2_ppm)} ppm`],
    ]);

    // Mega + tools (hide ibus numeric; show only as link via LED)
    const mega = data.mega || {};
    const tools = mega.tools || {};
    fillKV("mega_kv", [
      ["Movement", `${mega.movement || "--"}`],
      ["AIR Tool", toolStateText(tools.air)],
      ["WATER Tool", toolStateText(tools.water)],
      ["SOIL Tool", toolStateText(tools.soil)],
    ]);

    // Validation (from your validation module)
    const v = snap.validation || {};
    const airV = v.air || null;
    const waterV = v.water || null;
    const soilV = v.soil || null;

    fillKV("validation_kv", [
      ["AIR", validationLine("AIR", airV)],
      ["WATER", validationLine("WATER", waterV)],
      ["SOIL", validationLine("SOIL", soilV)],
    ]);

    // Status log
    const log = snap.status_log || [];
    const lines = log.map(x => {
      const t = new Date((x.ts || 0) * 1000).toLocaleTimeString();
      return `[${t}] ${x.msg}`;
    });
    document.getElementById("status_box").value = lines.join("\n");

  } catch (e) {
    document.getElementById("uiState").textContent = "DISCONNECTED";
  }
}

document.getElementById("runOn").addEventListener("click", async () => { await post("/api/run/on"); });
document.getElementById("runOff").addEventListener("click", async () => { await post("/api/run/off"); });

setInterval(refresh, 500);
refresh();
