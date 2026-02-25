import board
import busio
import adafruit_bno055
import time
import math


# =============================================================================
# EXCEPTIONS
# =============================================================================

class IMUSensorSetupError(Exception):
    pass

class IMUSensorReadError(Exception):
    pass


# =============================================================================
# MODULE STATE
# =============================================================================

GRAVITY = 9.80665  # m/s²

_IMU = None
_IMU_CONNECTED = False
_velocity = {"x": 0.0, "y": 0.0, "z": 0.0}
_last_read_ts = None

# Maps rover axis index [0=x, 1=y, 2=z] → sensor axis index
# e.g. _axis_map = [0, 2, 1] means rover_z = sensor_y
_axis_map = [0, 1, 2]  # identity (standard mount), overwritten by setup()


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _apply_axis_map(values):
    """Remap a sensor (x, y, z) tuple into the rover frame using _axis_map."""
    return (values[_axis_map[0]], values[_axis_map[1]], values[_axis_map[2]])


def _detect_gravity_axis(n_samples=10):
    """
    Average n_samples of raw acceleration and return the sensor axis index
    (0=x, 1=y, 2=z) that carries the most gravity.
    Falls back to 2 (Z) if readings fail.
    """
    totals = [0.0, 0.0, 0.0]
    count = 0
    for _ in range(n_samples):
        accel = _IMU.acceleration
        if accel and None not in accel:
            for i in range(3):
                totals[i] += abs(accel[i])
            count += 1
        time.sleep(0.02)

    if count == 0:
        return 2  # default: assume Z

    avgs = [totals[i] / count for i in range(3)]
    return max(range(3), key=lambda i: avgs[i])


# =============================================================================
# SENSOR FUNCTIONS
# =============================================================================

def setup():
    """
    Initialize BNO055 IMU over I2C.
    Auto-detects which sensor axis carries gravity at boot and remaps it to
    rover Z. The remaining two sensor axes fill rover X and Y in their natural
    order. No manual configuration needed when remounting the sensor.
    """
    global _IMU, _IMU_CONNECTED, _velocity, _last_read_ts, _axis_map

    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        _IMU = adafruit_bno055.BNO055_I2C(i2c)
    except Exception as e:
        raise IMUSensorSetupError(f"IMU init failed: {e}")

    # Short stabilisation pause before sampling gravity direction
    time.sleep(0.5)

    gravity_idx = _detect_gravity_axis()

    # Gravity axis → rover Z. Remaining sensor axes fill rover X, Y in order.
    remaining = [i for i in range(3) if i != gravity_idx]
    _axis_map = [remaining[0], remaining[1], gravity_idx]

    _velocity = {"x": 0.0, "y": 0.0, "z": 0.0}
    _last_read_ts = time.monotonic()
    _IMU_CONNECTED = True


def read():
    """
    Returns:
      g_force:  float            — total acceleration magnitude in g (scalar, axis-independent)
      velocity: {x, y, z} m/s   — integrated velocity in rover frame
    """
    global _velocity, _last_read_ts

    if not _IMU_CONNECTED or _IMU is None:
        raise IMUSensorReadError("IMU not connected")

    # Raw acceleration (includes gravity) — only used for g_force magnitude
    accel = _IMU.acceleration
    if accel is None or None in accel:
        raise IMUSensorReadError("Invalid accelerometer data")

    # Linear acceleration (gravity removed) for velocity integration
    lin_accel = _IMU.linear_acceleration
    if lin_accel is None or None in lin_accel:
        raise IMUSensorReadError("Invalid linear acceleration data")

    # g_force is a scalar magnitude — not affected by axis remapping
    ax, ay, az = accel
    g_force = math.sqrt(ax ** 2 + ay ** 2 + az ** 2) / GRAVITY

    # Remap linear acceleration to rover frame, then integrate
    lx, ly, lz = _apply_axis_map(lin_accel)
    now = time.monotonic()
    dt = now - _last_read_ts if _last_read_ts is not None else 0.0
    _last_read_ts = now

    _velocity["x"] += lx * dt
    _velocity["y"] += ly * dt
    _velocity["z"] += lz * dt

    return {
        "g_force":  round(g_force, 4),
        "velocity": {
            "x": round(_velocity["x"], 4),
            "y": round(_velocity["y"], 4),
            "z": round(_velocity["z"], 4),
        },
    }


def close():
    global _IMU_CONNECTED
    _IMU_CONNECTED = False

