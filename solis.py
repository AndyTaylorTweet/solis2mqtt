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
    publish False for a register we only read in order to derive something
            else from it, and which is not worth a topic of its own
    """

    def __init__(self, name, addr, words=1, scale=1, signed=False, unit='',
                 sane=None, publish=True):
        self.name = name
        self.addr = addr
        self.words = words
        self.scale = scale
        self.signed = signed
        self.unit = unit
        self.sane = sane
        self.publish = publish

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
# The inverter takes at most 100 registers per request and answers
# IllegalDataAddressError for more, which is why battery_power at 33149
# needs a second block rather than one wide read from 33029.
BLOCKS = [
    (33029, 66, [
        Register('energy_total',      33029, 2, 1, unit='kWh', sane=(0, 10000000)),
        Register('energy_this_month', 33031, 2, 1, unit='kWh', sane=(0, 1000000)),
        Register('energy_last_month', 33033, 2, 1, unit='kWh', sane=(0, 1000000)),
        Register('energy_today',      33035, 1, 0.1, unit='kWh', sane=(0, 1000)),
        Register('energy_yesterday',  33036, 1, 0.1, unit='kWh', sane=(0, 1000)),
        Register('energy_this_year',  33037, 2, 1, unit='kWh', sane=(0, 1000000)),
        Register('energy_last_year',  33039, 2, 1, unit='kWh', sane=(0, 1000000)),
        Register('pv_voltage',        33049, 1, 0.1, unit='V', sane=(0, 1000)),
        Register('pv_current',        33050, 1, 0.1, unit='A', sane=(0, 100)),
        Register('pv2_voltage',       33051, 1, 0.1, unit='V', sane=(0, 1000)),
        Register('pv2_current',       33052, 1, 0.1, unit='A', sane=(0, 100)),
        Register('pv_power',          33057, 2, 1, unit='W', sane=(0, 100000)),
        Register('grid_voltage',      33073, 1, 0.1, unit='V', sane=(0, 500)),
        Register('inv_power',         33079, 2, 1, signed=True, unit='W', sane=(-100000, 100000)),
        Register('sys_temp',          33093, 1, 0.1, unit='C', sane=(-40, 150)),
        Register('grid_frequency',    33094, 1, 0.01, unit='Hz', sane=(0, 100)),
    ]),
    (33130, 21, [
        Register('grid_power',      33130, 2, 1, signed=True, unit='W', sane=(-100000, 100000)),
        # Only tells us which way the battery is going; battery_charge,
        # battery_discharge and battery_power_signed carry that already.
        Register('battery_status',  33135, 1, 1, sane=(0, 1), publish=False),
        Register('battery_soc',     33139, 1, 1, unit='%', sane=(0, 100)),
        Register('battery_soh',     33140, 1, 1, unit='%', sane=(0, 100)),
        Register('battery_voltage', 33141, 1, 0.01, unit='V', sane=(0, 1000)),
        Register('battery_current', 33142, 1, 0.1, unit='A', sane=(0, 1000)),
        Register('inv_load',        33147, 1, 1, unit='W', sane=(0, 100000)),
        # Magnitude only; battery_status carries the direction. add_derived
        # combines the two into the signed battery_power we publish.
        Register('battery_magnitude', 33149, 2, 1, unit='W', sane=(0, 100000),
                 publish=False),
    ]),
]

# Identification, read once at startup rather than every poll.
# 35000 needs no address offset, and Solis document its codes in hex: the
# high byte is the protocol the inverter speaks, the low byte the model.
TYPE_REGISTER = 35000
SERIAL_REGISTER = 33004
SERIAL_WORDS = 8

# The register addresses above are the energy storage (ESINV-33000ID)
# protocol. A string inverter speaks 0x10 and puts entirely different
# things at these addresses, so its readings would be meaningless.
PROTOCOL_ENERGY_STORAGE = 0x20
PROTOCOLS = {
    0x10: 'string inverter (INV-3000ID / EPM-36000ID)',
    0x20: 'energy storage (ESINV-33000ID)',
}
MODELS = {
    0x30: '1 phase low voltage energy storage',
    0x31: '1 phase low voltage AC couple energy storage',
    0x40: '1 phase high voltage energy storage',
    0x50: '3 phase low voltage energy storage',
    0x60: '3 phase high voltage energy storage',
}
# The only model this register map has actually been checked against.
VERIFIED_MODEL = 0x30


# Read to derive other values from, but not published.
INTERNAL = {register.name
            for _, _, registers in BLOCKS
            for register in registers
            if not register.publish}


class TransientError(Exception):
    """A read failed in a way that is usually worth retrying."""


class UnsupportedInverter(Exception):
    """The inverter does not speak the protocol this register map assumes."""


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

    def identify(self, retries=4, retry_delay=6.0):
        """Read the model and serial, and check the protocol is one we speak.

        Raises UnsupportedInverter if the inverter reports a protocol
        other than energy storage, because every address in BLOCKS would
        then point at something else entirely. A read that simply fails
        raises TransientError; not being able to ask is not the same as
        being told no.
        """
        raw = self.read_block(TYPE_REGISTER, 1, retries=retries,
                              retry_delay=retry_delay)[0]
        protocol, model = raw >> 8, raw & 0xFF
        info = {
            'raw': raw,
            'protocol': protocol,
            'protocol_name': PROTOCOLS.get(protocol, 'unknown'),
            'model': model,
            'model_name': MODELS.get(model, 'unknown'),
            'serial': None,
        }
        if protocol != PROTOCOL_ENERGY_STORAGE:
            raise UnsupportedInverter(
                'inverter reports protocol 0x%02X (%s), but this register map is '
                'for 0x%02X (%s)'
                % (protocol, info['protocol_name'],
                   PROTOCOL_ENERGY_STORAGE, PROTOCOLS[PROTOCOL_ENERGY_STORAGE]))

        try:
            words = self.read_block(SERIAL_REGISTER, SERIAL_WORDS)
            serial = ''.join(chr(w >> 8) + chr(w & 0xFF) for w in words)
            info['serial'] = ''.join(c for c in serial if c.isprintable()).strip()
        except (TransientError, ValueError):
            pass  # Cosmetic only; not worth failing startup over.
        return info

    def read_all(self, inter_block_delay=0.5):
        """Read every mapped register and return a name -> value dict.

        Values that fall outside their plausible range are dropped, so a
        garbled read publishes nothing rather than poisoning a feed.
        Registers marked publish=False are used to derive other values and
        then dropped from the result.
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
        readings = add_derived(readings)
        return {name: value for name, value in readings.items()
                if name not in INTERNAL}


def add_derived(readings):
    """Add the values computed from other readings."""
    power = readings.get('battery_magnitude')
    status = readings.get('battery_status')
    if power is not None and status is not None:
        charging = status == BATTERY_CHARGING
        # Sign convention: negative into the battery, positive out of it.
        readings['battery_power'] = -power if charging else power
        readings['battery_charge'] = power if charging else 0
        readings['battery_discharge'] = 0 if charging else power

    pv1 = readings.get('pv_voltage'), readings.get('pv_current')
    pv2 = readings.get('pv2_voltage'), readings.get('pv2_current')
    if all(v is not None for v in pv1 + pv2):
        readings['pv_string_power'] = round(pv1[0] * pv1[1] + pv2[0] * pv2[1], 1)

    return readings
