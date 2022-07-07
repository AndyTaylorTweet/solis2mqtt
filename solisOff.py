#!/usr/bin/env python3

#	Project		: solisOnOff
#	Filename	: solisOnOff.py
#	Created by	: Andy Taylor
#	Created on	: 10/05/2022

import sys, time, logging
from pysolarmanv5.pysolarmanv5 import PySolarmanV5

# MODBUS server IP, port, ID and DogleID
MODBUS_SERVER = "1.2.3.4"
MODBUS_PORT = 8899
MODBUS_ID = 1
MODBUS_DONGLEID = 1234567890

# Debug
debug = 1

def collect():
  try:
    # Connect to MODBUS
    solis = PySolarmanV5(MODBUS_SERVER, MODBUS_DONGLEID, port=MODBUS_PORT, mb_slave_id=MODBUS_ID, verbose=1)

    # Scrape the data from MODBUS
    if debug:
      logging.info('Reading MODBUS')

    # Inverter Status Read=0x03 Write=0x06 (and -1 for register number)
    GRID_OFF = solis.write_single_coil(5000, 0x0000)
    INV_OFF = solis.write_holding_register(43006, 0xDE)

    # Debug
    if debug:
      print("Grid Status : ", repr(GRID_OFF))
      print("Inv Status  : ", repr(INV_OFF))

  except Exception:
    logging.error('Unable to read data from MODBUS')
    sys.exit(1)

if __name__ == '__main__':
  # Setup Logging
  logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler()])
  # Loop
  collect()
