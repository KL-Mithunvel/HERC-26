
<html>
<body>
<!--StartFragment--><html><h1>Sensor Code Architecture – MOVIS Rover (HERC-26)</h1><p>This document defines <strong>how all sensor code must be written</strong> for the MOVIS rover software stack.</p><p>The goal is:</p><ul><li><p>predictable behavior</p></li><li><p>safe failure handling</p></li><li><p>easy debugging</p></li><li><p>easy replacement of fake sensors with real hardware</p></li><li><p>zero crashes due to missing sensors</p></li></ul><p>This applies to <strong>all sensors</strong>: temperature, power meter, GPS, IMU, ADC, air sensor, Arduino Mega, etc.</p><hr><h2>1. Core Design Philosophy</h2><h3>1.1 Sensors do ONE job only</h3><p>A sensor module must:</p><ul><li><p>connect to its hardware (or simulate it)</p></li><li><p>read values</p></li><li><p>report errors</p></li></ul><p>A sensor module must <strong>NOT</strong>:</p><ul><li><p>print to console</p></li><li><p>log to files</p></li><li><p>talk to databases</p></li><li><p>know anything about UI or Flask</p></li><li><p>know anything about logging on/off</p></li></ul><p>All higher-level decisions are handled outside the sensor.</p><hr><h3>1.2 No sensor controls program flow</h3><p>A sensor:</p><ul><li><p>never exits the program</p></li><li><p>never stops the main loop</p></li><li><p>never blocks forever</p></li></ul><p>If a sensor fails:</p><ul><li><p>it throws an error</p></li><li><p>the system continues running</p></li></ul><hr><h2>2. Required Sensor Interface (Template)</h2><p>Every sensor module <strong>must expose the same interface</strong>.</p><h3>Mandatory functions</h3><pre><code class="language-python">setup()
read()
</code></pre><h3>Optional</h3><pre><code class="language-python">close()
</code></pre><hr><h2>3. Error Handling Rules</h2><h3>3.1 Each sensor defines its OWN errors</h3><p>Do <strong>not</strong> reuse generic errors.</p><p>Example:</p><pre><code class="language-python">class TempSetupError(Exception):
    pass

class TempReadError(Exception):
    pass
</code></pre><p>Why:</p><ul><li><p>makes debugging easy</p></li><li><p>error source is immediately clear</p></li><li><p>UI can show sensor-specific messages</p></li></ul><hr><h3>3.2 When to throw errors</h3>
Situation | What to do
-- | --
Sensor not found during setup | raise SensorSetupError
Sensor disconnected mid-run | raise SensorReadError
Bad / invalid data | raise SensorReadError
Temporary glitch | raise SensorReadError

<p>Never return garbage silently.</p><hr><h2>4. Template Sensor (Canonical Example)</h2><p>This is the <strong>official template</strong> all sensors must follow.</p><pre><code class="language-python"># sensors/example_sensor.py
import random

class ExampleSetupError(Exception):
    pass

class ExampleReadError(Exception):
    pass


_connected = False


def setup():
    global _connected

    # Simulate setup success
    _connected = True

    # Example setup failure:
    # raise ExampleSetupError("Sensor not found")


def read():
    if not _connected:
        raise ExampleReadError("Sensor not initialized")

    # Simulated 1–5% failure rate (dev mode)
    if random.random() &lt; 0.01:
        raise ExampleReadError("Simulated read failure")

    # Return raw sensor value(s)
    value = random.uniform(10.0, 50.0)
    return value


def close():
    global _connected
    _connected = False
</code></pre><hr><h2>5. Data Rules</h2><h3>5.1 What sensors return</h3><p>Sensors return:</p><ul><li><p>numbers</p></li><li><p>strings</p></li><li><p>dicts (for grouped values)</p></li></ul><p>Example:</p><pre><code class="language-python">return {
    "voltage_v": 24.1,
    "current_a": 3.2,
    "power_w": 77.1
}
</code></pre><p>Sensors <strong>do not</strong>:</p><ul><li><p>format strings</p></li><li><p>attach timestamps</p></li><li><p>attach logging flags</p></li></ul><hr><h3>5.2 Missing or invalid data</h3><p>If a sensor <strong>cannot</strong> produce valid data:</p><ul><li><p>throw an error</p></li><li><p>DO NOT return fake values</p></li><li><p>DO NOT return <code inline="">-1</code> inside sensor code</p></li></ul><p>Decisions like <code inline="">-1</code>, <code inline="">null</code>, or fallback values are handled later.</p><hr><h2>6. Development Mode vs Real Hardware</h2><h3>6.1 Dev (Fake) Sensors</h3><p>During development:</p><ul><li><p>sensors simulate realistic values</p></li><li><p>sensors simulate random failures (≈1%)</p></li><li><p>system behavior is tested without hardware</p></li></ul><p>This allows:</p><ul><li><p>UI development</p></li><li><p>API development</p></li><li><p>validation logic</p></li><li><p>database schema testing</p></li></ul><hr><h3>6.2 Switching to Real Hardware</h3><p>When hardware is ready:</p><ul><li><p>replace the fake sensor file with a real one</p></li><li><p>keep the <strong>same function names</strong></p></li><li><p>keep the <strong>same return structure</strong></p></li><li><p>keep the <strong>same error behavior</strong></p></li></ul><p>No other code should need changes.</p><hr><h2>7. How Sensors Are Used in the System</h2><h3>7.1 Sensor Stack</h3><p>Sensors are <strong>not called directly by UI or Flask</strong>.</p><p>Instead:</p><ul><li><p>a sensor stack calls <code inline="">read()</code> on each sensor</p></li><li><p>collects results</p></li><li><p>collects errors</p></li><li><p>builds a single snapshot</p></li></ul><p>Example snapshot:</p><pre><code class="language-json">{
  "ts": 1738123456.12,
  "run_enabled": true,
  "data": { ... },
  "health": { ... },
  "errors": { ... }
}
</code></pre><hr><h3>7.2 Logging</h3><p>Logging:</p><ul><li><p>happens continuously</p></li><li><p>logs every snapshot</p></li><li><p>includes <code inline="">run_enabled</code> flag</p></li><li><p>survives Wi-Fi disconnects</p></li></ul><p>Sensors do <strong>not</strong> know logging exists.</p><hr><h2>8. Status &amp; Debug Messages</h2><p>Sensors must <strong>not</strong> print status messages.</p><p>Instead:</p><ul><li><p>success/failure is inferred by higher layers</p></li><li><p>health changes are logged centrally</p></li><li><p>UI shows messages like:</p><ul><li><p>“GPS connected”</p></li><li><p>“ADC read error”</p></li><li><p>“Mega reconnected”</p></li></ul></li></ul><p>This avoids console spam and keeps history consistent.</p><hr><h2>9. Why This Architecture Was Chosen</h2><p>This design:</p><ul><li><p>prevents crashes during competition</p></li><li><p>allows partial sensor failure</p></li><li><p>allows UI disconnect without data loss</p></li><li><p>makes debugging fast</p></li><li><p>scales to more sensors easily</p></li><li><p>allows new team members to understand code quickly</p></li></ul><p>It is intentionally <strong>simple and strict</strong>.</p><hr><h2>10. Summary Rules (Read This If Nothing Else)</h2><ul><li><p>Sensors only do setup + read</p></li><li><p>Sensors throw errors, never print</p></li><li><p>Sensors never stop the program</p></li><li><p>All sensors follow the same template</p></li><li><p>Fake sensors first, real sensors later</p></li><li><p>One snapshot controls everything</p></li></ul><hr><!--EndFragment-->
</body>
</html>