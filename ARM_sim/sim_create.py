import math
import csv
from dataclasses import dataclass

import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, Button, TextBox
from matplotlib.patches import Rectangle

# USER PARAMETERS
L1 = 140.0  # mm
L2 = 140.0  # mm
LB = 55.0   # mm

DEFAULT_LIMITS = {
    "th1_min": -90, "th1_max":  90,
    "th2_min": -90, "th2_max":  90,
    "th3_min": -90, "th3_max":  90,
}

TIME_MIN = 0.0
TIME_MAX = 60.0

# DEFAULTS
BASE_X0 = 0.0  # mm
BASE_Y0 = 0.0  # mm

BOX_X0 = 120.0  # mm
BOX_Y0 = -60.0  # mm
BOX_W  = 80.0   # mm
BOX_H  = 60.0   # mm


def deg2rad(d):
    return d * math.pi / 180.0


def fk(th1_deg, th2_deg, th3_deg, base_xy=(0.0, 0.0)):
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


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def safe_float(s: str, fallback: float) -> float:
    try:
        return float(str(s).strip())
    except Exception:
        return fallback


@dataclass
class Pose:
    time_s: float
    th1: float
    th2: float
    th3: float


class ArmGUI:
    def __init__(self):
        self.poses: list[Pose] = []
        self.limits = DEFAULT_LIMITS.copy()
        self._lock = False

        # STATE: BASE + BOX
        self.base_x = float(BASE_X0)
        self.base_y = float(BASE_Y0)

        self.box_x0 = float(BOX_X0)
        self.box_y0 = float(BOX_Y0)
        self.box_w = float(BOX_W)
        self.box_h = float(BOX_H)

        self.fig = plt.figure(figsize=(13, 7))

        # ---------------- PLOT (LEFT) ----------------
        self.ax = self.fig.add_axes([0.05, 0.22, 0.62, 0.74])
        self.ax.set_aspect("equal", adjustable="box")
        self.ax.grid(True)

        r = (L1 + L2 + LB) * 1.25
        self.ax.set_xlim(-r, r)
        self.ax.set_ylim(-r, r)

        (self.line_links,) = self.ax.plot([], [], marker="o", linewidth=3)
        (self.line_bucket,) = self.ax.plot([], [], marker="o", linewidth=3)
        (self.base_marker,) = self.ax.plot([], [], "o", ms=10)

        self.txt = self.ax.text(
            0.02, 0.98, "", transform=self.ax.transAxes, va="top", ha="left"
        )

        # Yellow target box
        self.target_box = Rectangle(
            (self.box_x0, self.box_y0),
            self.box_w,
            self.box_h,
            facecolor="yellow",
            edgecolor="goldenrod",
            alpha=0.35,
            lw=2,
        )
        self.ax.add_patch(self.target_box)

        # ---------------- RIGHT PANEL LAYOUT ----------------
        # A clean vertical stack with consistent spacing
        rx = 0.72
        rw = 0.26
        row_h = 0.045
        gap = 0.015

        def row(y):
            return [rx, y, rw, row_h]

        # -------- Angles sliders
        self.s_th1 = Slider(self.fig.add_axes(row(0.88)), "θ1 (deg)",
                            self.limits["th1_min"], self.limits["th1_max"], valinit=0)
        self.s_th2 = Slider(self.fig.add_axes(row(0.82)), "θ2 (deg)",
                            self.limits["th2_min"], self.limits["th2_max"], valinit=0)
        self.s_th3 = Slider(self.fig.add_axes(row(0.76)), "θ3 (deg)",
                            self.limits["th3_min"], self.limits["th3_max"], valinit=0)

        # -------- Time slider
        self.s_t = Slider(self.fig.add_axes(row(0.68)), "t (s)", TIME_MIN, TIME_MAX, valinit=0.0)

        for s in (self.s_th1, self.s_th2, self.s_th3, self.s_t):
            s.on_changed(self.update)

        # -------- Text inputs for angles/time (2 columns)
        # Left column: θ1 θ2 θ3 t
        # Right column: Base X Base Y
        col1_x = rx
        col2_x = rx + rw * 0.52
        col_w = rw * 0.48
        tb_h = 0.045

        def tb(colx, y):
            return [colx, y, col_w, tb_h]

        self.tb_th1 = TextBox(self.fig.add_axes(tb(col1_x, 0.62)), "θ1", initial="0")
        self.tb_th2 = TextBox(self.fig.add_axes(tb(col1_x, 0.56)), "θ2", initial="0")
        self.tb_th3 = TextBox(self.fig.add_axes(tb(col1_x, 0.50)), "θ3", initial="0")
        self.tb_t   = TextBox(self.fig.add_axes(tb(col1_x, 0.44)), "t",  initial="0.0")

        self.tb_base_x = TextBox(self.fig.add_axes(tb(col2_x, 0.62)), "Base X", initial=str(BASE_X0))
        self.tb_base_y = TextBox(self.fig.add_axes(tb(col2_x, 0.56)), "Base Y", initial=str(BASE_Y0))

        for tbx in (self.tb_th1, self.tb_th2, self.tb_th3, self.tb_t):
            tbx.on_submit(lambda _: self._apply_textboxes())

        # Set Base button (under base boxes)
        self.b_set_base = Button(self.fig.add_axes([col2_x, 0.50, col_w, 0.05]), "Set Base")
        self.b_set_base.on_clicked(self.set_base)

        # -------- Yellow box controls (2 columns)
        self.tb_box_x0 = TextBox(self.fig.add_axes(tb(col1_x, 0.34)), "Box X0", initial=str(BOX_X0))
        self.tb_box_y0 = TextBox(self.fig.add_axes(tb(col2_x, 0.34)), "Box Y0", initial=str(BOX_Y0))
        self.tb_box_w  = TextBox(self.fig.add_axes(tb(col1_x, 0.28)), "Box W",  initial=str(BOX_W))
        self.tb_box_h  = TextBox(self.fig.add_axes(tb(col2_x, 0.28)), "Box H",  initial=str(BOX_H))

        self.b_set_box = Button(self.fig.add_axes([rx, 0.22, rw, 0.055]), "Set Yellow Box")
        self.b_set_box.on_clicked(self.set_yellow_box)

        # -------- Pose buttons (3 in a row)
        b_y = 0.14
        b_h = 0.06
        b_w = (rw - 0.02) / 2

        self.b_save = Button(self.fig.add_axes([rx, b_y, b_w, b_h]), "Save Pose")
        self.b_clear = Button(self.fig.add_axes([rx + b_w + 0.02, b_y, b_w, b_h]), "Clear")

        self.b_export = Button(self.fig.add_axes([rx, 0.06, rw, 0.06]), "Export CSV")

        self.b_save.on_clicked(self.save_pose)
        self.b_clear.on_clicked(self.clear_poses)
        self.b_export.on_clicked(self.export_csv)

        # ---------------- POSE LIST (BOTTOM LEFT) ----------------
        self.pose_box = self.fig.add_axes([0.05, 0.03, 0.62, 0.16])
        self.pose_box.axis("off")
        self.pose_text = self.pose_box.text(0, 1, "", va="top", family="monospace")

        self.update(None)

    def _apply_textboxes(self):
        if self._lock:
            return
        self._lock = True
        try:
            self.s_th1.set_val(clamp(safe_float(self.tb_th1.text, 0.0), self.s_th1.valmin, self.s_th1.valmax))
            self.s_th2.set_val(clamp(safe_float(self.tb_th2.text, 0.0), self.s_th2.valmin, self.s_th2.valmax))
            self.s_th3.set_val(clamp(safe_float(self.tb_th3.text, 0.0), self.s_th3.valmin, self.s_th3.valmax))
            self.s_t.set_val(clamp(safe_float(self.tb_t.text, 0.0), self.s_t.valmin, self.s_t.valmax))
        finally:
            self._lock = False

    def _sync_textboxes(self):
        if self._lock:
            return
        self._lock = True
        try:
            self.tb_th1.set_val(f"{self.s_th1.val:.2f}")
            self.tb_th2.set_val(f"{self.s_th2.val:.2f}")
            self.tb_th3.set_val(f"{self.s_th3.val:.2f}")
            self.tb_t.set_val(f"{self.s_t.val:.3f}")
        finally:
            self._lock = False

    def set_base(self, _):
        self.base_x = safe_float(self.tb_base_x.text, self.base_x)
        self.base_y = safe_float(self.tb_base_y.text, self.base_y)
        self.update(None)

    def set_yellow_box(self, _):
        self.box_x0 = safe_float(self.tb_box_x0.text, self.box_x0)
        self.box_y0 = safe_float(self.tb_box_y0.text, self.box_y0)
        self.box_w = max(0.0, safe_float(self.tb_box_w.text, self.box_w))
        self.box_h = max(0.0, safe_float(self.tb_box_h.text, self.box_h))

        self.target_box.set_xy((self.box_x0, self.box_y0))
        self.target_box.set_width(self.box_w)
        self.target_box.set_height(self.box_h)

        self.update(None)

    def update(self, _):
        self._sync_textboxes()

        th1, th2, th3 = self.s_th1.val, self.s_th2.val, self.s_th3.val
        t_now = self.s_t.val

        p0, p1, p2, pb = fk(th1, th2, th3, base_xy=(self.base_x, self.base_y))
        self.line_links.set_data([p0[0], p1[0], p2[0]], [p0[1], p1[1], p2[1]])
        self.line_bucket.set_data([p2[0], pb[0]], [p2[1], pb[1]])
        self.base_marker.set_data([p0[0]], [p0[1]])

        self.txt.set_text(
            f"θ1={th1:.1f}°  θ2={th2:.1f}°  θ3={th3:.1f}°\n"
            f"t (save time) = {t_now:.3f} s\n"
            f"Base = ({self.base_x:.1f}, {self.base_y:.1f}) mm\n"
            f"Saved poses: {len(self.poses)}"
        )

        self._update_pose_list()
        self.fig.canvas.draw_idle()

    def save_pose(self, _):
        self.poses.append(Pose(
            time_s=float(self.s_t.val),
            th1=float(self.s_th1.val),
            th2=float(self.s_th2.val),
            th3=float(self.s_th3.val),
        ))
        self.update(None)

    def clear_poses(self, _):
        self.poses.clear()
        self.update(None)

    def export_csv(self, _):
        if not self.poses:
            return
        poses = sorted(self.poses, key=lambda p: p.time_s)
        with open("arm_poses_export.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time_s", "th1_deg", "th2_deg", "th3_deg"])
            for p in poses:
                w.writerow([f"{p.time_s:.3f}", f"{p.th1:.3f}", f"{p.th2:.3f}", f"{p.th3:.3f}"])
        print("Exported: arm_poses_export.csv")

    def _update_pose_list(self):
        if not self.poses:
            self.pose_text.set_text(
                "Saved Poses: (none)\n"
                "Meaning of time:\n"
                "- t is the exact time when this pose must be reached.\n"
                "- Playback will interpolate between poses."
            )
            return

        poses = sorted(self.poses, key=lambda p: p.time_s)[-10:]
        lines = [" time(s) |  θ1   θ2   θ3"]
        for p in poses:
            lines.append(f"{p.time_s:7.2f} | {p.th1:5.1f} {p.th2:5.1f} {p.th3:5.1f}")
        self.pose_text.set_text("\n".join(lines))


if __name__ == "__main__":
    ArmGUI()
    plt.show()