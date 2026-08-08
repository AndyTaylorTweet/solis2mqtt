#!/usr/bin/env python3

#	Project		: solis2mqtt
#	Filename	: solisctl.py
#	Created by	: Andy Taylor
#	Created on	: 10/05/2022

"""Switch the Solis inverter and its grid connection on or off.

Modbus register notes: read=0x03, write=0x06, and the register numbers
here are already offset by -1 as the inverter expects.
"""

import argparse
import logging
import sys

import solis_config as config_module
import solis

log = logging.getLogger('solisctl')

INVERTER_REGISTER = 43006
INVERTER_ON = 0xBE
INVERTER_OFF = 0xDE

GRID_COIL = 5000
GRID_ON = 0xFF00
GRID_OFF = 0x0000


def switch(client, state):
    """Apply the requested state.

    The ordering is deliberate and differs between on and off: bring the
    inverter up before the grid, and drop the grid before the inverter.
    """
    if state == 'on':
        inverter = client.write_holding_register(INVERTER_REGISTER, INVERTER_ON)
        grid = client.write_single_coil(GRID_COIL, GRID_ON)
    else:
        grid = client.write_single_coil(GRID_COIL, GRID_OFF)
        inverter = client.write_holding_register(INVERTER_REGISTER, INVERTER_OFF)
    return inverter, grid


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('state', choices=['on', 'off'],
                        help='switch the inverter and grid on or off')
    parser.add_argument('-y', '--yes', action='store_true',
                        help='do not ask for confirmation')
    args = parser.parse_args(argv)

    try:
        cfg = config_module.load()
    except config_module.ConfigError as err:
        config_module.setup_logging(force_level='INFO')
        log.error('%s', err)
        return 2

    config_module.setup_logging(cfg)

    if not args.yes and sys.stdin.isatty():
        answer = input('Switch the inverter %s at %s? [y/N] '
                       % (args.state.upper(), cfg['modbus']['host']))
        if answer.strip().lower() not in ('y', 'yes'):
            log.info('Aborted')
            return 1

    inverter = solis.Inverter(
        cfg['modbus']['host'], cfg['modbus']['serial'],
        port=cfg['modbus']['port'], slave_id=cfg['modbus']['slave_id'],
        timeout=cfg['modbus']['timeout'],
    )

    try:
        inverter_result, grid_result = switch(inverter.connect(), args.state)
    except Exception as err:
        log.error('Failed to switch inverter %s: %s', args.state, err)
        return 1
    finally:
        inverter.disconnect()

    log.info('Inverter %s -> %s', args.state, inverter_result)
    log.info('Grid %s -> %s', args.state, grid_result)
    return 0


if __name__ == '__main__':
    sys.exit(main())
