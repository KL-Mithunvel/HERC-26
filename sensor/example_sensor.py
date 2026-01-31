# sensors/example_sensor.py
# Generic fake sensor template: setup() once, read() many times.
# - read() returns a random value
# - 5% chance read() raises an error

import random

class FakeSensorSetupError(Exception):
    pass

class FakeSensorReadError(Exception):
    pass

_connected = False

# Tune these as needed
MIN_VALUE = 0.0
MAX_VALUE = 100.0
FAIL_PROB = 0.05  # 5%


def setup():
    """
    Call once. Sets up internal state.
    Optional: simulate setup failure by changing FAIL_PROB or adding a condition.
    """
    global _connected
    _connected = True


def read():
    """
    Call repeatedly. Returns a float.
    5% chance of throwing FakeSensorReadError.
    """
    if not _connected:
        raise FakeSensorReadError("Fake sensor not reading up")


    return MIN_VALUE + (MAX_VALUE - MIN_VALUE) * random.random()


def close():
    global _connected
    _connected = False
