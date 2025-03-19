#!/usr/bin/env python3

#	Project		: solis2mqtt
#	Filename	: solis2mqtt.py
#	Created by	: Andy Taylor
#	Created on	: 10/05/2022

import sys, time, logging
import paho.mqtt.client as mqtt
from pysolarmanv5.pysolarmanv5 import PySolarmanV5
from time import sleep

# MQTT server IP, port, topic, keepalive
CLEAN_SESSION=True
MQTT_SERVER = "127.0.0.1"
MQTT_PORT = 1883
MQTT_TOPIC = "emon/solis"
MQTT_KEEPALIVE = 60
MQTT_USER = "emonpi"
MQTT_PASS = "emonpimqtt2016"

# MODBUS server IP, port, ID and DogleID
MODBUS_SERVER = "1.2.3.4"
MODBUS_PORT = 8899
MODBUS_ID = 1
MODBUS_DONGLEID = 1234567890

# How often should we poll
check_interval = 11

# Debug
debug = 0

def collect():
  try:
    # Connect to MQTT
    if debug:
      logging.info('Connecting to MQTT Server')
    mqttc = mqtt.Client()
    mqttc.username_pw_set(MQTT_USER, MQTT_PASS)

    # Connect to MODBUS
    modbus = PySolarmanV5(MODBUS_SERVER, MODBUS_DONGLEID, port=MODBUS_PORT, mb_slave_id=MODBUS_ID, verbose=0)

    # Scrape the data from MODBUS
    if debug:
      logging.info('Reading MODBUS')

    # Battery
    BATTERY_SOC = modbus.read_input_register_formatted(register_addr=33139, quantity=1, signed=0)
    BATTERY_POWER = modbus.read_input_register_formatted(register_addr=33149, quantity=2, signed=0)
    BATTERY_STATUS = modbus.read_input_register_formatted(register_addr=33135, quantity=1, scale=1, signed=0)
    if repr(BATTERY_STATUS) == "1":
      BATTERY_DISCHARGE = BATTERY_POWER
      BATTERY_CHARGE = 0
    elif repr(BATTERY_STATUS) == "0":
      BATTERY_DISCHARGE = 0
      BATTERY_CHARGE = BATTERY_POWER
    else:
      BATTERY_DISCHARGE = 0
      BATTERY_CHARGE = 0

    # Solar
    PV_VOLTS = modbus.read_input_register_formatted(register_addr=33049, quantity=1, scale=0.1, signed=0 )
    PV_AMPS = modbus.read_input_register_formatted(register_addr=33050, quantity=1, scale=0.1, signed=0 )
    PV_POWER = modbus.read_input_register_formatted(register_addr=33057, quantity=2, scale=1, signed=0 )

    # Grid
    GRID_POWER = modbus.read_input_register_formatted(register_addr=33130, quantity=2, scale=1, signed=1 )
    INV_POWER = modbus.read_input_register_formatted(register_addr=33079, quantity=2, scale=1, signed=1 )
    INV_LOAD = modbus.read_input_register_formatted(register_addr=33147, quantity=1, scale=1, signed=0 )

    # System
    #SYS_TEMP = modbus.read_input_register_formatted(register_addr=33093, quantity=1, scale=0.1, signed=0 )

    # Debug
    if debug:
      print("Battery SOC       : ", repr(BATTERY_SOC))
      print("Battery Discharge : ", repr(BATTERY_DISCHARGE))
      print("Battery Charge    : ", repr(BATTERY_CHARGE))
      print("Battery Status    : ", repr(BATTERY_STATUS))
      print("PV Voltage        : ", repr(PV_VOLTS))
      print("PV Current        : ", repr(PV_AMPS))
      print("PV Power          : ", repr(PV_POWER))
      print("Grid Power        : ", repr(GRID_POWER))
      print("Inverter Power    : ", repr(INV_POWER))
      print("Inverter Load     : ", repr(INV_LOAD))
      #print("Sys Temp          : ", repr(SYS_TEMP))

    # For the absesnse of doubt, I reaslise how dumb this looks to connect
    # publish one topic and disconnect, but something in paho-mqtt changed
    # that has made this a requirement :(
    if isinstance(BATTERY_SOC, (int, float)) and 0 <= BATTERY_SOC <= 100:
      # Let's only log sane values shall we
      mqttc.connect(MQTT_SERVER, MQTT_PORT, MQTT_KEEPALIVE)
      mqttc.publish(MQTT_TOPIC + '/' + 'battery_soc', repr(BATTERY_SOC))
      mqttc.disconnect()
    mqttc.connect(MQTT_SERVER, MQTT_PORT, MQTT_KEEPALIVE)
    mqttc.publish(MQTT_TOPIC + '/' + 'battery_discharge',repr(BATTERY_DISCHARGE))
    mqttc.disconnect()
    mqttc.connect(MQTT_SERVER, MQTT_PORT, MQTT_KEEPALIVE)
    mqttc.publish(MQTT_TOPIC + '/' + 'battery_charge', repr(BATTERY_CHARGE))
    mqttc.disconnect()
    mqttc.connect(MQTT_SERVER, MQTT_PORT, MQTT_KEEPALIVE)
    mqttc.publish(MQTT_TOPIC + '/' + 'pv_voltage', repr(PV_VOLTS))
    mqttc.disconnect()
    mqttc.connect(MQTT_SERVER, MQTT_PORT, MQTT_KEEPALIVE)
    mqttc.publish(MQTT_TOPIC + '/' + 'pv_current', repr(PV_AMPS))
    mqttc.disconnect()
    mqttc.connect(MQTT_SERVER, MQTT_PORT, MQTT_KEEPALIVE)
    mqttc.publish(MQTT_TOPIC + '/' + 'pv_power', repr(PV_POWER))
    mqttc.disconnect()
    mqttc.connect(MQTT_SERVER, MQTT_PORT, MQTT_KEEPALIVE)
    mqttc.publish(MQTT_TOPIC + '/' + 'grid_power', repr(GRID_POWER))
    mqttc.disconnect()
    mqttc.connect(MQTT_SERVER, MQTT_PORT, MQTT_KEEPALIVE)
    mqttc.publish(MQTT_TOPIC + '/' + 'inv_power', repr(INV_POWER))
    mqttc.disconnect()
    mqttc.connect(MQTT_SERVER, MQTT_PORT, MQTT_KEEPALIVE)
    mqttc.publish(MQTT_TOPIC + '/' + 'inv_load', repr(INV_LOAD))
    mqttc.disconnect()

  except Exception:
    logging.error('Unable to read data from MODBUS')
    sys.exit(1)

if __name__ == '__main__':
  # Setup Logging
  logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler()])
  # Loop
  while True:
    collect()
    sleep(check_interval)
