import math
import csv
from dataclasses import dataclass

import matplotlib
matplotlib.use("TkAgg")

import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, Button

# ================= ARM PARAMETERS =================
L1, L2, LB = 140.0, 140.0, 55.0
TIME_MIN, TIME_MAX = 0.0, 20.0


# ================= KINEMATICS =================
def deg2rad(d):
    return d * math.pi / 180.0


def fk(th1, th2, th3):
    t1, t2, t3 = map(deg2rad, (th1, th2, th3))
    x0, y0 = 0.0, 0.0
    x1, y1 = L1 * math.cos(t1), L1 * math.sin(t1)
    x2, y2 = x1 + L2 * math.cos(t1 + t2), y1 + L2 * math.sin(t1 + t2)
    xb, yb = x2 + LB * math.cos(t1 + t2 + t3), y2 + LB * math.sin(t1 + t2 + t3)
    return (x0, y0), (x1, y1), (x2, y2), (xb, yb)


# ================= DATA =================
@dataclass
class Pose:
    time_s: float
    th1: float   # sweep (0–180)
    th2: float
    th3: float


# ================= GUI =================
class ArmGUI:
    def __init__(self):
        self.poses = []

        # ---- state (NO drawing here) ----
        self.ref = [0.0, 0.0, 0.0]
        self.sweep = [0.0, 0.0, 0.0]

        self.fig = plt.figure(figsize=(12, 8))

        # ================= ARM PLOT =================
        self.ax = self.fig.add_axes([0.05, 0.30, 0.55, 0.65])
        self.ax.set_aspect("equal")
        self.ax.grid(True)

        r = (L1 + L2 + LB) * 1.2
        self.ax.set_xlim(-r, r)
        self.ax.set_ylim(-r, r)

        self.links, = self.ax.plot([], [], "-o", lw=3)
        self.bucket, = self.ax.plot([], [], "-o", lw=3)

        # ================= SLIDERS =================
        x, w, h = 0.65, 0.30, 0.025
        dy, y = 0.055, 0.90

        def slider(label, vmin, vmax, vinit):
            nonlocal y
            s = Slider(self.fig.add_axes([x, y, w, h]),
                       label, vmin, vmax, valinit=vinit)
            y -= dy
            return s

        self.th1_0 = slider("θ1 reference (0°)", -180, 180, -90)
        self.th1   = slider("θ1 sweep (0–180)", 0, 180, 0)
        y -= 0.02

        self.th2_0 = slider("θ2 reference (0°)", -180, 180, -90)
        self.th2   = slider("θ2 sweep (0–180)", 0, 180, 0)
        y -= 0.02

        self.th3_0 = slider("θ3 reference (0°)", -180, 180, -90)
        self.th3   = slider("θ3 sweep (0–180)", 0, 180, 0)
        y -= 0.04

        self.s_t = slider("Δt to next pose (s)", TIME_MIN, TIME_MAX, 1.0)

        # ================= BUTTONS =================
        self.b_save = Button(self.fig.add_axes([0.65, 0.22, 0.14, 0.06]), "Save Pose")
        self.b_clear = Button(self.fig.add_axes([0.81, 0.22, 0.14, 0.06]), "Clear")
        self.b_export = Button(self.fig.add_axes([0.65, 0.14, 0.30, 0.06]), "Export CSV")

        self.b_save.on_clicked(self.save_pose)
        self.b_clear.on_clicked(self.clear_poses)
        self.b_export.on_clicked(self.export_csv)

        # ================= POSE DISPLAY =================
        self.pose_box = self.fig.add_axes([0.05, 0.05, 0.90, 0.18])
        self.pose_box.axis("off")
        self.pose_text = self.pose_box.text(
            0.0, 1.0, "", va="top", family="monospace"
        )

        # ---- slider callbacks: STATE ONLY ----
        for s in (
            self.th1_0, self.th1,
            self.th2_0, self.th2,
            self.th3_0, self.th3
        ):
            s.on_changed(self.read_state)

        # ================= TIMER (THE FIX) =================
        self.timer = self.fig.canvas.new_timer(interval=30)  # ~33 FPS
        self.timer.add_callback(self.redraw)
        self.timer.start()

        self.update_pose_list()

    # ---- read sliders (NO drawing) ----
    def read_state(self, _):
        self.ref[0] = self.th1_0.val
        self.ref[1] = self.th2_0.val
        self.ref[2] = self.th3_0.val
        self.sweep[0] = self.th1.val
        self.sweep[1] = self.th2.val
        self.sweep[2] = self.th3.val

    # ---- redraw ONLY here ----
    def redraw(self):
        th1 = self.ref[0] + self.sweep[0]
        th2 = self.ref[1] + self.sweep[1]
        th3 = self.ref[2] + self.sweep[2]

        p0, p1, p2, pb = fk(th1, th2, th3)

        self.links.set_data([p0[0], p1[0], p2[0]],
                            [p0[1], p1[1], p2[1]])
        self.bucket.set_data([p2[0], pb[0]],
                             [p2[1], pb[1]])

        self.fig.canvas.draw_idle()

    # ================= POSE HANDLING =================
    def save_pose(self, _):
        self.poses.append(Pose(
            self.s_t.val,
            self.th1.val,
            self.th2.val,
            self.th3.val
        ))
        self.update_pose_list()

    def clear_poses(self, _):
        self.poses.clear()
        self.update_pose_list()

    def export_csv(self, _):
        if not self.poses:
            return
        with open("arm_poses_sweep.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time_s", "th1", "th2", "th3"])
            for p in self.poses:
                w.writerow([p.time_s, p.th1, p.th2, p.th3])
        print("Exported: arm_poses_sweep.csv")

    def update_pose_list(self):
        if not self.poses:
            self.pose_text.set_text("Saved poses: (none)")
            return
        lines = ["#  Δt(s)   θ1   θ2   θ3", "-----------------------"]
        for i, p in enumerate(self.poses, 1):
            lines.append(f"{i:<2} {p.time_s:6.2f} {p.th1:5.1f} {p.th2:5.1f} {p.th3:5.1f}")
        self.pose_text.set_text("\n".join(lines))


# ================= RUN =================
if __name__ == "__main__":
    ArmGUI()
    plt.show()
