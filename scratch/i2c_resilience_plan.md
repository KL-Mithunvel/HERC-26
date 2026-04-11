# Plan: Make sensor loop resilient to I2C bus errors

## Context

The entire I2C bus (SDA/SCL) is unreliable — likely a bad solder joint. From testing:
- Any sleep between reads causes `Errno 121` (Remote I/O error)
- Back-to-back reads mostly work but still fail ~5-10% of the time
- **Re-initialising the bus fixes it** (adc_tester Test 3 confirmed this)
- **All I2C sensors are affected**: ADS1115 (0x49), BNO055 (0x28), TMP102 (0x48)

BNO055 additional issue: sensor stuck in invalid OPR_MODE 0x10 (valid range 0x00–0x0C), accel reads all zeros. Needs software reset + mode set on reconnect.

The bus will be resoldered, but the code must be resilient regardless — bad connections can recur in the field.

## Problems Found

### Problem 1: Reconnect doesn't actually reinit the I2C bus (ADS1115)
- `real_stack._try_reconnect("soil", _soil)` calls `_soil.close()` → `_soil.setup()`
- `soil.close()` sets its own `_CONNECTED = False` but does **not** call `_adc.close()`
- `soil.setup()` calls `_adc.setup()` which checks `if _CONNECTED: return` — **skips reinit** because ads1115 still thinks it's connected
- **Result**: reconnect never reinits the I2C bus, so the bus stays locked up forever
- Same issue for ph.py and power.py.

### Problem 2: soil.read_filtered() is guaranteed to fail on flaky I2C
- `read_filtered(samples=11, delay=0.01)` makes 11 reads with **10ms sleep between each**
- We proved that even 1ms sleep kills the bus
- Cache expires mid-loop, triggering a real I2C read after a delay — which fails

### Problem 3: ads1115 doesn't mark itself disconnected on total failure
- When all 3 retries fail in `read_all()`, it raises but leaves `_CONNECTED = True`
- Next call to `read_all()` tries again on the broken bus object instead of forcing a reinit

### Problem 4: BNO055 can get stuck in invalid mode
- bno055_tester showed OPR_MODE = 0x10 (not a valid mode), accel all zeros
- Adafruit driver doesn't recover from this — it just gets Errno 121
- `imu.setup()` doesn't attempt a software reset before init
- If the sensor is in a bad state after power glitch or bus error, it stays broken until power cycle

## Proposed Changes

### Change 1: `sensor/ads1115.py` — self-healing bus reinit
- When all retries in `read_all()` fail, set `_CONNECTED = False` (marks bus as dead)
- This means the next `setup()` call from any sensor's reconnect will actually reinit the I2C bus
- Make `close()` properly deinit the `busio.I2C` object and reset state

### Change 2: `sensor/soil.py`, `sensor/ph.py`, `sensor/power.py` — close propagates to ads1115
- `close()` should call `_adc.close()` so the bus gets reinited on reconnect

### Change 3: `sensor/soil.py` — make read_filtered() tolerant of partial failures
- Wrap each sample in try/except, collect however many succeed
- Return median of successful samples (minimum 1 needed)
- Remove the 10ms delay between samples — read as fast as possible since delays kill the bus

### Change 4: `sensor/imu.py` — software reset on setup
- In `setup()`, before initialising the Adafruit driver, do a raw smbus software reset:
  - Write 0x20 to register 0x3F (SYS_TRIGGER) to reset the BNO055
  - Wait 650ms for the sensor to reboot
  - Then proceed with normal Adafruit `BNO055_I2C()` init (which sets NDOF mode)
- This recovers from invalid mode states without requiring a physical power cycle
- Guard the smbus import with try/except (already available on Pi via python3-smbus)

## Files to modify

1. **`sensor/ads1115.py`** — `read_all()`: set `_CONNECTED = False` on total failure. `close()`: deinit the I2C bus object.
2. **`sensor/soil.py`** — `close()`: propagate to `_adc.close()`. `read_filtered()`: tolerate partial failures, remove delay.
3. **`sensor/ph.py`** — `close()`: propagate to `_adc.close()`.
4. **`sensor/power.py`** — `close()`: propagate to `_adc.close()`.
5. **`sensor/imu.py`** — `setup()`: add smbus software reset before Adafruit driver init.

## Verification

1. Run `scratch/adc_tester.py` — Test 3 (re-init recovery) should still pass
2. Run `python main_sim.py` — dev stack unaffected, dashboard works
3. On Pi: run `python main.py` — all I2C sensors should recover from bus errors instead of staying permanently offline
4. Run `python tests/test_read_all.py` on Pi — sensors should show OK/FLAKY not permanent OFFLINE
5. Run `scratch/bno055_tester.py` — Test 5 (Adafruit driver) should work after software reset is added to setup()