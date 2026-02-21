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

        # ---------------- NEW STATE ----------------
        self.base_x = float(BASE_X0)
        self.base_y = float(BASE_Y0)

        self.box_x0 = float(BOX_X0)
        self.box_y0 = float(BOX_Y0)
        self.box_w = float(BOX_W)
        self.box_h = float(BOX_H)

        self.fig = plt.figure(figsize=(12, 7))

        #  Plot
        self.ax = self.fig.add_axes([0.06, 0.30, 0.62, 0.66])
        self.ax.set_aspect("equal", adjustable="box")
        self.ax.grid(True)

        r = (L1 + L2 + LB) * 1.25
        self.ax.set_xlim(-r, r)
        self.ax.set_ylim(-r, r)

        (self.line_links,) = self.ax.plot([], [], marker="o", linewidth=3)
        (self.line_bucket,) = self.ax.plot([], [], marker="o", linewidth=3)
        (self.base_marker,) = self.ax.plot([], [], "o", ms=10)  # base marker

        self.txt = self.ax.text(
            0.02, 0.98, "", transform=self.ax.transAxes, va="top", ha="left"
        )

        # ---------------- YELLOW TARGET BOX ----------------
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

        #  Sliders
        self.s_th1 = Slider(self.fig.add_axes([0.74, 0.86, 0.22, 0.03]),
                            "θ1 (deg)", self.limits["th1_min"], self.limits["th1_max"], valinit=0)
        self.s_th2 = Slider(self.fig.add_axes([0.74, 0.78, 0.22, 0.03]),
                            "θ2 (deg)", self.limits["th2_min"], self.limits["th2_max"], valinit=0)
        self.s_th3 = Slider(self.fig.add_axes([0.74, 0.70, 0.22, 0.03]),
                            "θ3 (deg)", self.limits["th3_min"], self.limits["th3_max"], valinit=0)

        self.s_t = Slider(self.fig.add_axes([0.74, 0.58, 0.22, 0.03]),
                          "t (s)", TIME_MIN, TIME_MAX, valinit=0.0)

        for s in (self.s_th1, self.s_th2, self.s_th3, self.s_t):
            s.on_changed(self.update)

        #   TextBoxes (angles/time)
        self.tb_th1 = TextBox(self.fig.add_axes([0.74, 0.90, 0.10, 0.04]), "θ1", initial="0")
        self.tb_th2 = TextBox(self.fig.add_axes([0.74, 0.82, 0.10, 0.04]), "θ2", initial="0")
        self.tb_th3 = TextBox(self.fig.add_axes([0.74, 0.74, 0.10, 0.04]), "θ3", initial="0")
        self.tb_t   = TextBox(self.fig.add_axes([0.74, 0.62, 0.10, 0.04]), "t",  initial="0.0")

        for tb in (self.tb_th1, self.tb_th2, self.tb_th3, self.tb_t):
            tb.on_submit(lambda _: self._apply_textboxes())

        # ---------------- NEW: BASE ENTRY ----------------
        self.tb_base_x = TextBox(self.fig.add_axes([0.86, 0.90, 0.10, 0.04]), "Base X", initial=str(BASE_X0))
        self.tb_base_y = TextBox(self.fig.add_axes([0.86, 0.82, 0.10, 0.04]), "Base Y", initial=str(BASE_Y0))
        self.b_set_base = Button(self.fig.add_axes([0.86, 0.74, 0.10, 0.06]), "Set Base")
        self.b_set_base.on_clicked(self.set_base)

        # ---------------- NEW: YELLOW BOX ENTRY ----------------
        self.tb_box_x0 = TextBox(self.fig.add_axes([0.74, 0.50, 0.10, 0.04]), "Box X0", initial=str(BOX_X0))
        self.tb_box_y0 = TextBox(self.fig.add_axes([0.86, 0.50, 0.10, 0.04]), "Box Y0", initial=str(BOX_Y0))
        self.tb_box_w  = TextBox(self.fig.add_axes([0.74, 0.45, 0.10, 0.04]), "Box W",  initial=str(BOX_W))
        self.tb_box_h  = TextBox(self.fig.add_axes([0.86, 0.45, 0.10, 0.04]), "Box H",  initial=str(BOX_H))
        self.b_set_box = Button(self.fig.add_axes([0.74, 0.39, 0.22, 0.06]), "Set Yellow Box")
        self.b_set_box.on_clicked(self.set_yellow_box)

        #  Buttons (pose)
        self.b_save = Button(self.fig.add_axes([0.74, 0.31, 0.10, 0.06]), "Save Pose")
        self.b_clear = Button(self.fig.add_axes([0.86, 0.31, 0.10, 0.06]), "Clear")
        self.b_export = Button(self.fig.add_axes([0.74, 0.23, 0.22, 0.06]), "Export CSV")

        self.b_save.on_clicked(self.save_pose)
        self.b_clear.on_clicked(self.clear_poses)
        self.b_export.on_clicked(self.export_csv)

        #  Pose list
        self.pose_box = self.fig.add_axes([0.06, 0.06, 0.90, 0.14])
        self.pose_box.axis("off")
        self.pose_text = self.pose_box.text(0, 1, "", va="top", family="monospace")

        self.update(None)

    def _apply_textboxes(self):
        if self._lock:
            return
        self._lock = True
        try:
            def f(tb):
                return safe_float(tb.text, 0.0)

            self.s_th1.set_val(clamp(f(self.tb_th1), self.s_th1.valmin, self.s_th1.valmax))
            self.s_th2.set_val(clamp(f(self.tb_th2), self.s_th2.valmin, self.s_th2.valmax))
            self.s_th3.set_val(clamp(f(self.tb_th3), self.s_th3.valmin, self.s_th3.valmax))
            self.s_t.set_val(clamp(f(self.tb_t), self.s_t.valmin, self.s_t.valmax))
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
        """Read Base X/Y textboxes and update base position."""
        self.base_x = safe_float(self.tb_base_x.text, self.base_x)
        self.base_y = safe_float(self.tb_base_y.text, self.base_y)
        self.update(None)

    def set_yellow_box(self, _):
        """Read box textboxes and update the yellow rectangle."""
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