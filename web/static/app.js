async function post(url) {
  const res = await fetch(url, { method: "POST" });
  return res.json();
}

function setLight(name, ok) {
  const el = document.getElementById("light_" + name);
  if (!el) return;
  el.classList.remove("green", "red");
  el.classList.add(ok ? "green" : "red");
}

function fmt(obj) {
  return JSON.stringify(obj, null, 2);
}

async function refresh() {
  try {
    const res = await fetch("/api/snapshot");
    const snap = await res.json();

    document.getElementById("meta").textContent = `ts=${snap.ts?.toFixed?.(2) ?? snap.ts}  |  errors=${Object.keys(snap.errors || {}).length}`;
    document.getElementById("runState").textContent = `RUN: ${snap.run_enabled ? "ON" : "OFF"}`;

    const health = snap.health || {};
    ["power","temperature","gps","imu","adc","air","mega"].forEach(k => {
      const ok = health[k]?.ok === true;
      setLight(k, ok);
    });

    // boxes
    document.getElementById("power_box").textContent = fmt(snap.data?.power ?? "--");
    document.getElementById("temp_box").textContent = fmt(snap.data?.temperature ?? "--");
    document.getElementById("gps_box").textContent = fmt(snap.data?.gps ?? "--");
    document.getElementById("imu_box").textContent = fmt(snap.data?.imu ?? "--");
    document.getElementById("adc_box").textContent = fmt(snap.data?.adc ?? "--");
    document.getElementById("air_box").textContent = fmt(snap.data?.air ?? "--");
    document.getElementById("mega_box").textContent = fmt(snap.data?.mega ?? "--");
    document.getElementById("timer_box").textContent = fmt(snap.data?.timers ?? "--");

    // status log
    const log = snap.status_log || [];
    const lines = log.map(x => {
      const t = new Date((x.ts || 0) * 1000).toLocaleTimeString();
      return `[${t}] ${x.msg}`;
    });
    document.getElementById("status_box").value = lines.join("\n");

  } catch (e) {
    // If UI loses connection, just show something.
    document.getElementById("meta").textContent = "UI fetch failed (check connection)";
  }
}

document.getElementById("runOn").addEventListener("click", async () => { await post("/api/run/on"); });
document.getElementById("runOff").addEventListener("click", async () => { await post("/api/run/off"); });

setInterval(refresh, 500);
refresh();
