import csv
import math
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Button, Slider, TextBox
from matplotlib.animation import FuncAnimation
from matplotlib.patches import Rectangle

#   USER SETTINGS
CSV_PATH = "arm_poses_5.csv"  # <-- HARD CODE YOUR CSV FILE PATH HERE
L1 = 140.0   # mm
L2 = 130.0   # mm
LB = 55.0    # mm (bucket display length)
FPS = 60     # viewer refresh rate (Hz)

# ---------------- NEW DEFAULTS ----------------
BASE_X0 = 0.0  # mm
BASE_Y0 = 0.0  # mm

# Yellow target box (lower-left + size)
BOX_X0 = 120.0  # mm
BOX_Y0 = -60.0  # mm
BOX_W  = 80.0   # mm
BOX_H  = 60.0   # mm


def deg2rad(d):
    return d * math.pi / 180.0


def fk(th1_deg, th2_deg, th3_deg, base_xy=(0.0, 0.0)):
    """Forward kinematics with a movable base (base_xy = (bx, by))."""
    bx, by = base_xy

    th1 = deg2rad(th1_deg)
    th2 = deg2rad(th2_deg)
    th3 = deg2rad(th3_deg)

    x0, y0 = bx, by
    x1 = x0 + L1 * math.cos(th1)
    y1 = y0 + L1 * math.sin(th1)
    x2 = x1 + L2 * math.cos(th1 + th2)
    y2 = y1 + L2 * math.sin(th1 + th2)
    xb = x2 + LB * math.cos(th1 + th2 + th3)
    yb = y2 + LB * math.sin(th1 + th2 + th3)
    return (x0, y0), (x1, y1), (x2, y2), (xb, yb)


#   Load CSV
t, th1, th2, th3 = [], [], [], []
with open(CSV_PATH, "r", newline="") as f:
    r = csv.DictReader(f)
    for row in r:
        t.append(float(row["time_s"]))
        th1.append(float(row["th1_deg"]))
        th2.append(float(row["th2_deg"]))
        th3.append(float(row["th3_deg"]))

if len(t) < 2:
    raise ValueError("CSV must have at least 2 rows.")

t = np.array(t)
th1 = np.array(th1)
th2 = np.array(th2)
th3 = np.array(th3)

# Ensure strictly increasing time
order = np.argsort(t)
t, th1, th2, th3 = t[order], th1[order], th2[order], th3[order]
if np.any(np.diff(t) <= 0):
    raise ValueError("time_s must be strictly increasing (no duplicates).")

t0 = float(t[0])
t_end = float(t[-1])

# ---------------- STATE ----------------
playing = False
current_time = t0

base_x = float(BASE_X0)
base_y = float(BASE_Y0)

box_x0 = float(BOX_X0)
box_y0 = float(BOX_Y0)
box_w  = float(BOX_W)
box_h  = float(BOX_H)


def angles_at(time_s: float):
    """Linear interpolation of angles at an arbitrary time."""
    a1 = np.interp(time_s, t, th1)
    a2 = np.interp(time_s, t, th2)
    a3 = np.interp(time_s, t, th3)
    return float(a1), float(a2), float(a3)


#  Figure
fig = plt.figure(figsize=(12, 7))
ax = fig.add_axes([0.06, 0.22, 0.62, 0.74])
ax.set_aspect("equal", adjustable="box")
ax.grid(True)

R = (L1 + L2 + LB) * 1.1
ax.set_xlim(-R * 0.4, R * 1.1)
ax.set_ylim(-R * 0.8, R * 0.9)

(line_links,) = ax.plot([], [], "o-", lw=3)
(line_bucket,) = ax.plot([], [], "o-", lw=3)
(base_marker,) = ax.plot([], [], "o", ms=10)  # base marker
txt = ax.text(0.02, 0.98, "", transform=ax.transAxes, ha="left", va="top")

# Yellow rectangular target box
target_box = Rectangle(
    (box_x0, box_y0), box_w, box_h,
    facecolor="yellow", edgecolor="goldenrod", alpha=0.35, lw=2
)
ax.add_patch(target_box)


def draw_at(time_s: float):
    a1, a2, a3 = angles_at(time_s)
    p0, p1, p2, pb = fk(a1, a2, a3, base_xy=(base_x, base_y))

    line_links.set_data([p0[0], p1[0], p2[0]], [p0[1], p1[1], p2[1]])
    line_bucket.set_data([p2[0], pb[0]], [p2[1], pb[1]])

    base_marker.set_data([p0[0]], [p0[1]])

    txt.set_text(
        f"t = {time_s:.2f} s / {t_end:.2f} s\n"
        f"θ1 = {a1:.1f}°   θ2 = {a2:.1f}°   θ3 = {a3:.1f}°\n"
        f"Base = ({base_x:.1f}, {base_y:.1f}) mm"
    )


def refresh_box_patch():
    target_box.set_xy((box_x0, box_y0))
    target_box.set_width(box_w)
    target_box.set_height(box_h)


# ---------------- CONTROLS (RIGHT PANEL) ----------------
ax_play = fig.add_axes([0.72, 0.86, 0.25, 0.06])
ax_reset = fig.add_axes([0.72, 0.79, 0.25, 0.06])
btn_play = Button(ax_play, "Play / Pause")
btn_reset = Button(ax_reset, "Reset")

ax_speed = fig.add_axes([0.72, 0.72, 0.25, 0.04])
speed = Slider(ax_speed, "Speed", 0.1, 2.0, valinit=0.5)

ax_scrub = fig.add_axes([0.06, 0.08, 0.91, 0.04])
scrub = Slider(ax_scrub, "Time (s)", t0, t_end, valinit=t0)

# ---- Base coordinate input
ax_bx = fig.add_axes([0.72, 0.62, 0.12, 0.05])
ax_by = fig.add_axes([0.85, 0.62, 0.12, 0.05])
tb_bx = TextBox(ax_bx, "Base X", initial=str(BASE_X0))
tb_by = TextBox(ax_by, "Base Y", initial=str(BASE_Y0))

ax_set_base = fig.add_axes([0.72, 0.56, 0.25, 0.05])
btn_set_base = Button(ax_set_base, "Set Base")

# ---- Yellow box input (lower-left + size)
ax_box_x = fig.add_axes([0.72, 0.46, 0.12, 0.05])
ax_box_y = fig.add_axes([0.85, 0.46, 0.12, 0.05])
tb_box_x = TextBox(ax_box_x, "Box X0", initial=str(BOX_X0))
tb_box_y = TextBox(ax_box_y, "Box Y0", initial=str(BOX_Y0))

ax_box_w = fig.add_axes([0.72, 0.40, 0.12, 0.05])
ax_box_h = fig.add_axes([0.85, 0.40, 0.12, 0.05])
tb_box_w = TextBox(ax_box_w, "Box W", initial=str(BOX_W))
tb_box_h = TextBox(ax_box_h, "Box H", initial=str(BOX_H))

ax_set_box = fig.add_axes([0.72, 0.34, 0.25, 0.05])
btn_set_box = Button(ax_set_box, "Set Yellow Box")


def on_play(_):
    global playing
    playing = not playing


def on_reset(_):
    global playing, current_time
    playing = False
    current_time = t0
    scrub.set_val(t0)   # triggers draw via slider callback


def on_scrub(val):
    global current_time
    current_time = float(val)
    draw_at(current_time)
    fig.canvas.draw_idle()


def safe_float(s: str, fallback: float):
    try:
        return float(str(s).strip())
    except Exception:
        return fallback


def on_set_base(_):
    global base_x, base_y
    base_x = safe_float(tb_bx.text, base_x)
    base_y = safe_float(tb_by.text, base_y)
    draw_at(current_time)
    fig.canvas.draw_idle()


def on_set_box(_):
    global box_x0, box_y0, box_w, box_h
    box_x0 = safe_float(tb_box_x.text, box_x0)
    box_y0 = safe_float(tb_box_y.text, box_y0)
    box_w  = max(0.0, safe_float(tb_box_w.text, box_w))
    box_h  = max(0.0, safe_float(tb_box_h.text, box_h))
    refresh_box_patch()
    draw_at(current_time)
    fig.canvas.draw_idle()


btn_play.on_clicked(on_play)
btn_reset.on_clicked(on_reset)
scrub.on_changed(on_scrub)

btn_set_base.on_clicked(on_set_base)
btn_set_box.on_clicked(on_set_box)

# Initial draw
refresh_box_patch()
draw_at(current_time)


def update(_frame_idx):
    global current_time, playing

    if playing:
        dt = (1.0 / FPS) * speed.val
        current_time += dt

        if current_time >= t_end:
            current_time = t_end
            playing = False

        scrub.eventson = False
        scrub.set_val(current_time)
        scrub.eventson = True

        draw_at(current_time)

    return line_links, line_bucket, base_marker, txt, target_box


ani = FuncAnimation(fig, update, interval=1000 / FPS, blit=False)
plt.show()