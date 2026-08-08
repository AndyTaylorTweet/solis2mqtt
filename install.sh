#!/bin/bash
#
#	Project		: solis2mqtt
#	Filename	: install.sh
#
# Sets up the virtualenv, config file and systemd unit. Safe to re-run:
# an existing config.yaml is never overwritten.

set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${INSTALL_DIR}/.venv"
CONFIG="${INSTALL_DIR}/config.yaml"
SERVICE_NAME="solis2mqtt.service"
RUN_AS="${RUN_AS:-pi}"

if [ "$(id -u)" -ne 0 ]; then
    echo "Please run with sudo." >&2
    exit 1
fi

# Recent Raspberry Pi OS / Debian mark the system Python as externally
# managed (PEP 668), so pip refuses to install into it. A virtualenv keeps
# our dependencies self-contained and out of the way of apt.
echo "==> Creating virtualenv in ${VENV}"
python3 -m venv "${VENV}"
"${VENV}/bin/pip" install --quiet --upgrade pip
echo "==> Installing dependencies"
"${VENV}/bin/pip" install --quiet -r "${INSTALL_DIR}/requirements.txt"

if [ ! -f "${CONFIG}" ]; then
    echo "==> Creating ${CONFIG} from the example"
    cp "${INSTALL_DIR}/config.yaml.example" "${CONFIG}"
    echo "    EDIT IT before starting the service (modbus.host and modbus.serial)."
else
    echo "==> Keeping existing ${CONFIG}"
fi

# The config holds the MQTT password, so keep it readable only by the
# account the service runs as.
chown "${RUN_AS}" "${CONFIG}"
chmod 600 "${CONFIG}"

echo "==> Installing systemd unit"
ln -sf "${INSTALL_DIR}/${SERVICE_NAME}" "/etc/systemd/system/${SERVICE_NAME}"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"

echo
echo "Done. Check ${CONFIG}, then:"
echo "    sudo systemctl start ${SERVICE_NAME}"
echo "    journalctl -u ${SERVICE_NAME} -f"
