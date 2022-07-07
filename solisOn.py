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

    # Inverter Control
    INV_ON = solis.write_holding_register(43006, 0xBE)
    GRID_ON = solis.write_single_coil(5000, 0xFF00)

    # Debug
    if debug:
      print("Inverter Status : ", repr(INV_ON))
      print("Grid Status     : ", repr(GRID_ON))

  except Exception:
    logging.error('Unable to read data from MODBUS')
    sys.exit(1)

if __name__ == '__main__':
  # Setup Logging
  logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler()])
  # Loop
  collect()
