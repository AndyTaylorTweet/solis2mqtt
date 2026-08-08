#	Project		: solis2mqtt
#	Filename	: solis.py
#	Created by	: Andy Taylor

"""Solis inverter access over the Solarman V5 protocol.

The register map is declarative so a metric can be added by describing it
rather than by adding another round trip to the loop. Reads are grouped
into two contiguous blocks: the dongle copes far better with two requests
per poll than with one request per metric, which is what used to cause it
to lock up while it was busy talking to the Solis cloud.
"""

import logging
import time

from pysolarmanv5.pysolarmanv5 import PySolarmanV5

log = logging.getLogger(__name__)

# Battery status register values.
BATTERY_CHARGING = 0
BATTERY_DISCHARGING = 1


class Register:
    """One value in the inverter's input register map.

    addr    first register address
    words   number of 16 bit registers (2 = a 32 bit value, high word first)
    scale   multiplier applied to the raw value
    signed  interpret the combined raw value as two's complement
    sane    (min, max) plausible range; readings outside it are discarded
    """

    def __init__(self, name, addr, words=1, scale=1, signed=False, unit='', sane=None):
        self.name = name
        self.addr = addr
        self.words = words
        self.scale = scale
        self.signed = signed
        self.unit = unit
        self.sane = sane

    def decode(self, block_start, words):
        """Pull this register's value out of an already-read block."""
        offset = self.addr - block_start
        raw = 0
        for index in range(self.words):
            raw = (raw << 16) | words[offset + index]
        if self.signed:
            limit = 1 << (16 * self.words)
            if raw >= limit >> 1:
                raw -= limit
        value = raw * self.scale
        # Keep integers as integers so MQTT payloads stay tidy.
        return round(value, 2) if isinstance(self.scale, float) else value

    def is_sane(self, value):
        if self.sane is None:
            return True
        return self.sane[0] <= value <= self.sane[1]


# Contiguous blocks to read. Each is (start, quantity, [registers]).
# Both ranges were verified against the inverter; reading the whole
# 33049-33150 span in one go is rejected with IllegalDataAddress.
BLOCKS = [
    (33049, 45, [
        Register('pv_voltage',   33049, 1, 0.1, unit='V', sane=(0, 1000)),
        Register('pv_current',   33050, 1, 0.1, unit='A', sane=(0, 100)),
        Register('pv2_voltage',  33051, 1, 0.1, unit='V', sane=(0, 1000)),
        Register('pv2_current',  33052, 1, 0.1, unit='A', sane=(0, 100)),
        Register('pv_power',     33057, 2, 1, unit='W', sane=(0, 100000)),
        Register('inv_power',    33079, 2, 1, signed=True, unit='W', sane=(-100000, 100000)),
        Register('sys_temp',     33093, 1, 0.1, unit='C', sane=(-40, 150)),
    ]),
    (33130, 21, [
        Register('grid_power',      33130, 2, 1, signed=True, unit='W', sane=(-100000, 100000)),
        Register('battery_status',  33135, 1, 1, sane=(0, 1)),
        Register('battery_soc',     33139, 1, 1, unit='%', sane=(0, 100)),
        Register('battery_voltage', 33141, 1, 0.01, unit='V', sane=(0, 1000)),
        Register('battery_current', 33142, 1, 0.1, unit='A', sane=(0, 1000)),
        Register('inv_load',        33147, 1, 1, unit='W', sane=(0, 100000)),
        Register('battery_power',   33149, 2, 1, unit='W', sane=(0, 100000)),
    ]),
]


class TransientError(Exception):
    """A read failed in a way that is usually worth retrying."""


class Inverter:
    """A lazily-connected Solarman V5 client with retry on transient faults."""

    def __init__(self, host, serial, port=8899, slave_id=1, timeout=10):
        self.host = host
        self.serial = serial
        self.port = port
        self.slave_id = slave_id
        self.timeout = timeout
        self._client = None

    def connect(self):
        if self._client is None:
            log.debug('Connecting to inverter at %s:%s', self.host, self.port)
            self._client = PySolarmanV5(
                self.host, self.serial,
                port=self.port, mb_slave_id=self.slave_id,
                verbose=0, socket_timeout=self.timeout,
            )
        return self._client

    def disconnect(self):
        """Drop the socket so the next poll reconnects from scratch."""
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass  # Already gone; nothing useful to do about it.
            self._client = None

    def read_block(self, start, quantity, retries=1, retry_delay=1.0):
        """Read one contiguous register block, retrying transient failures."""
        last_error = None
        for attempt in range(retries + 1):
            try:
                return self.connect().read_input_registers(
                    register_addr=start, quantity=quantity)
            except Exception as err:
                last_error = err
                log.debug('Read of %s+%s failed (attempt %s): %s',
                          start, quantity, attempt + 1, err)
                # The dongle drops the connection when it locks up, so
                # rebuild the socket rather than reusing a dead one.
                self.disconnect()
                if attempt < retries:
                    time.sleep(retry_delay)
        raise TransientError('read of %s registers at %s failed: %s'
                             % (quantity, start, last_error))

    def read_all(self, inter_block_delay=0.5):
        """Read every mapped register and return a name -> value dict.

        Values that fall outside their plausible range are dropped, so a
        garbled read publishes nothing rather than poisoning a feed.
        """
        readings = {}
        for index, (start, quantity, registers) in enumerate(BLOCKS):
            if index:
                # Give the dongle a moment between requests; back to back
                # reads are noticeably more likely to come back empty.
                time.sleep(inter_block_delay)
            words = self.read_block(start, quantity)
            for register in registers:
                value = register.decode(start, words)
                if register.is_sane(value):
                    readings[register.name] = value
                else:
                    log.warning('Discarding implausible %s reading: %s%s',
                                register.name, value, register.unit)
        return add_derived(readings)


def add_derived(readings):
    """Add the values computed from other readings."""
    power = readings.get('battery_power')
    status = readings.get('battery_status')
    if power is not None and status is not None:
        charging = status == BATTERY_CHARGING
        readings['battery_charge'] = power if charging else 0
        readings['battery_discharge'] = 0 if charging else power
        # Signed convenience value: positive charging, negative discharging.
        readings['battery_power_signed'] = power if charging else -power

    pv1 = readings.get('pv_voltage'), readings.get('pv_current')
    pv2 = readings.get('pv2_voltage'), readings.get('pv2_current')
    if all(v is not None for v in pv1 + pv2):
        readings['pv_string_power'] = round(pv1[0] * pv1[1] + pv2[0] * pv2[1], 1)

    return readings
