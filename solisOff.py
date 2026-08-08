#!/usr/bin/env python3

#	Project		: solis2mqtt
#	Filename	: solisOff.py
#	Created by	: Andy Taylor
#	Created on	: 10/05/2022

"""Switch the inverter off. Kept for compatibility; see solisctl.py."""

import sys

import solisctl

if __name__ == '__main__':
    sys.exit(solisctl.main(['off']))
