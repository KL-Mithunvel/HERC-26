import time
from pymodbus.client import ModbusSerialClient

def init(port="/dev/ttyUSB0", slave_id=1, baudrate=9600, parity="N", stopbits=1, bytesize=8, timeout=1):
    """
    Returns (client, slave_id) or (None, slave_id) if not found.
    """
    try:
        client = ModbusSerialClient(
            port=port,
            baudrate=baudrate,
            parity=parity,
            stopbits=stopbits,
            bytesize=bytesize,
            timeout=timeout,
        )
        if not client.connect():
            return None, slave_id
        return client, slave_id
    except Exception:
        return None, slave_id

def _read_regs(client, slave_id, address, count):
    try:
        return client.read_holding_registers(address=address, count=count, slave=slave_id)
    except TypeError:
        return client.read_holding_registers(address, count, unit=slave_id)

def read(client, slave_id):
    """
    Returns dict, never throws.
    Assumes:
      reg0 = voltage*10
      reg1 = current*100
      reg2 = power (W)
    """
    if client is None:
        return {"ok": False, "msg": "Power meter not found"}

    try:
        voltage = _read_regs(client, slave_id, 0, 1)
        current = _read_regs(client, slave_id, 1, 1)
        power   = _read_regs(client, slave_id, 2, 1)

        if voltage.isError() or current.isError() or power.isError():
            return {"ok": False, "msg": "Power meter read error"}

        v = voltage.registers[0] / 10.0
        c = current.registers[0] / 100.0
        p = float(power.registers[0])

        return {"ok": True, "voltage_v": v, "current_a": c, "power_w": p}
    except Exception:
        return {"ok": False, "msg": "Power meter read failed"}

def close(client):
    try:
        if client is not None:
            client.close()
    except Exception:
        pass

if __name__ == "__main__":
    client, sid = init()
    while True:
        print(read(client, sid))
        time.sleep(1)
