import math
import time
from dataclasses import dataclass

import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, Button

# ================= ARM PARAMETERS =================
L1, L2, LB = 140.0, 140.0, 55.0
INIT_MOVE_TIME = 1.5


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


# ================= TRAJECTORY =================
@dataclass
class Pose:
    dt: float
    th1: float
    th2: float
    th3: float


trajectory = [
    Pose(3.02, 180, 159.7, 150.6),
    Pose(3.05, 31.9, 83.4, 30.3),
    Pose(3.05, 0, 0, 20.9),
    Pose(3.05, 0, 49.4, 104.7),
    Pose(2.05, 0, 100.0, 40.9),
    Pose(2.05, 55.3, 100.0, 0),
    Pose(2.05, 109.7, 61.9, 0),
    Pose(2.05, 115.0, 180, 0),
    Pose(1.15, 115.0, 180, 87.2),
    Pose(2.33, 180, 180, 123.4),
]


# ================= GUI =================
class ArmSimulator:
    def __init__(self):
        self.fig = plt.figure(figsize=(12, 7))

        # ---- Plot ----
        self.ax = self.fig.add_axes([0.05, 0.20, 0.55, 0.70])
        self.ax.set_aspect("equal")
        self.ax.grid(True)

        r = (L1 + L2 + LB) * 1.2
        self.ax.set_xlim(-r, r)
        self.ax.set_ylim(-r, r)

        self.links, = self.ax.plot([], [], "-o", lw=3)
        self.bucket, = self.ax.plot([], [], "-o", lw=3)

        # ---- Sliders ----
        self.ref1 = Slider(self.fig.add_axes([0.65, 0.80, 0.30, 0.03]),
                           "θ1 reference", -180, 180, valinit=-90)
        self.ref2 = Slider(self.fig.add_axes([0.65, 0.72, 0.30, 0.03]),
                           "θ2 reference", -180, 180, valinit=-90)
        self.ref3 = Slider(self.fig.add_axes([0.65, 0.64, 0.30, 0.03]),
                           "θ3 reference", -180, 180, valinit=-90)

        # ---- Button ----
        self.btn = Button(self.fig.add_axes([0.70, 0.48, 0.20, 0.08]), "SIMULATE")
        self.btn.on_clicked(self.simulate)

        # ---- State ----
        self.cur = [self.ref1.val, self.ref2.val, self.ref3.val]
        self.simulating = False

        # ---- Slider callbacks ----
        self.ref1.on_changed(self.on_slider_change)
        self.ref2.on_changed(self.on_slider_change)
        self.ref3.on_changed(self.on_slider_change)

        self.draw_arm()

    def on_slider_change(self, _):
        if self.simulating:
            return
        self.cur = [self.ref1.val, self.ref2.val, self.ref3.val]
        self.draw_arm()

    def draw_arm(self):
        p0, p1, p2, pb = fk(*self.cur)
        self.links.set_data([p0[0], p1[0], p2[0]],
                            [p0[1], p1[1], p2[1]])
        self.bucket.set_data([p2[0], pb[0]],
                             [p2[1], pb[1]])
        plt.pause(0.001)

    def move_linear(self, target, duration):
        start = self.cur.copy()
        t0 = time.time()

        while True:
            t = (time.time() - t0) / duration
            if t >= 1.0:
                break
            for i in range(3):
                self.cur[i] = start[i] + t * (target[i] - start[i])
            self.draw_arm()

        self.cur = target.copy()
        self.draw_arm()

    def simulate(self, _):
        self.simulating = True

        first = [
            self.ref1.val + trajectory[0].th1,
            self.ref2.val + trajectory[0].th2,
            self.ref3.val + trajectory[0].th3,
        ]
        self.move_linear(first, INIT_MOVE_TIME)

        for pose in trajectory[1:]:
            target = [
                self.ref1.val + pose.th1,
                self.ref2.val + pose.th2,
                self.ref3.val + pose.th3,
            ]
            self.move_linear(target, pose.dt)

        self.simulating = False


# ================= RUN =================
if __name__ == "__main__":
    ArmSimulator()
    plt.show()
