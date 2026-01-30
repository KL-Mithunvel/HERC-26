// web/static/obstacles.js
async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  return res.json();
}

function setText(id, txt) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = txt || "";
}

document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("saveEvent");
  if (!btn) return;

  btn.addEventListener("click", async () => {
    const obstacleId = document.getElementById("obstacle_id").value;
    const action = document.getElementById("action").value;

    setText("event_msg", "Saving...");

    try {
      const out = await postJSON("/api/event", {
        obstacle_id: Number(obstacleId),
        action: action
      });

      if (!out.ok) {
        setText("event_msg", `Save failed: ${out.error || "unknown error"}`);
        return;
      }

      setText("event_msg", out.msg || "Saved");
    } catch (e) {
      setText("event_msg", "Save failed (network error)");
    }
  });
});
