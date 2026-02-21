import board
import busio
import adafruit_bno055
import time
import math

class IMUSensorSetupError(Exception):
    pass

class IMUSensorReadError(Exception):
    pass


GRAVITY = 9.80665  # m/s²
IMU = None
IMU_CONNECTED = False


def setup():
    global IMU, IMU_CONNECTED
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        IMU = adafruit_bno055.BNO055_I2C(i2c)
        IMU_CONNECTED = True
    except Exception as e:
        raise IMUSensorSetupError(f"IMU init failed: {e}")


def read_gforce():
    if not IMU_CONNECTED or IMU is None:
        raise IMUSensorReadError("IMU not connected")

    accel = IMU.acceleration  # m/s² (includes gravity)
    if accel is None or None in accel:
        raise IMUSensorReadError("Invalid accelerometer data")

    ax, ay, az = accel

    gx = ax / GRAVITY
    gy = ay / GRAVITY
    gz = az / GRAVITY

    g_mag = math.sqrt(gx**2 + gy**2 + gz**2)

    return {
        "gx": round(gx, 4),
        "gy": round(gy, 4),
        "gz": round(gz, 4),
        "g_magnitude": round(g_mag, 4)
    }


def close():
    global IMU_CONNECTED
    IMU_CONNECTED = False


if __name__ == "__main__":
    setup()
    try:
        while True:
            print(read_gforce())
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopped by user")
    finally:
        close()
