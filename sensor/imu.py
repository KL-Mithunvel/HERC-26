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


# =============================================================================
# SENSOR FUNCTIONS
# =============================================================================

def setup():
    """Initialize BNO055 IMU over I2C."""
    global _IMU, _IMU_CONNECTED, _velocity, _last_read_ts
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        _IMU = adafruit_bno055.BNO055_I2C(i2c)
        _IMU_CONNECTED = True
        _velocity = {"x": 0.0, "y": 0.0, "z": 0.0}
        _last_read_ts = time.monotonic()
    except Exception as e:
        raise IMUSensorSetupError(f"IMU init failed: {e}")


def read():
    """
    Return full IMU snapshot dict matching the snapshot schema:
      acceleration: {x, y, z}  m/s²  (raw, includes gravity)
      orientation:  {roll, pitch, yaw}  degrees
      g_force:      float  (magnitude in g)
      velocity:     {x, y, z}  m/s  (integrated from linear acceleration)
    """
    global _velocity, _last_read_ts

    if not _IMU_CONNECTED or _IMU is None:
        raise IMUSensorReadError("IMU not connected")

    # Raw acceleration (includes gravity) in m/s²
    accel = _IMU.acceleration
    if accel is None or None in accel:
        raise IMUSensorReadError("Invalid accelerometer data")
    ax, ay, az = accel

    # Euler angles — BNO055 returns (heading/yaw, roll, pitch) in degrees
    euler = _IMU.euler
    if euler is None or None in euler:
        raise IMUSensorReadError("Invalid euler data")
    yaw, roll, pitch = euler

    # Linear acceleration (gravity removed) for velocity integration
    lin_accel = _IMU.linear_acceleration
    if lin_accel is None or None in lin_accel:
        raise IMUSensorReadError("Invalid linear acceleration data")
    lax, lay, laz = lin_accel

    # Integrate velocity
    now = time.monotonic()
    dt = now - _last_read_ts if _last_read_ts is not None else 0.0
    _last_read_ts = now
    _velocity["x"] += lax * dt
    _velocity["y"] += lay * dt
    _velocity["z"] += laz * dt

    g_force = math.sqrt((ax / GRAVITY) ** 2 + (ay / GRAVITY) ** 2 + (az / GRAVITY) ** 2)

    return {
        "acceleration": {"x": round(ax, 4), "y": round(ay, 4), "z": round(az, 4)},
        "orientation":  {"roll": round(roll, 2), "pitch": round(pitch, 2), "yaw": round(yaw, 2)},
        "g_force":      round(g_force, 4),
        "velocity":     {
            "x": round(_velocity["x"], 4),
            "y": round(_velocity["y"], 4),
            "z": round(_velocity["z"], 4),
        },
    }


def close():
    global _IMU_CONNECTED
    _IMU_CONNECTED = False


# =============================================================================
# MAIN — run directly on Pi to verify sensor
# =============================================================================

if __name__ == "__main__":
    setup()
    try:
        while True:
            print(read())
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopped")
    finally:
        close()
