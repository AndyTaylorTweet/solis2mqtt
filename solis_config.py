#	Project		: solis2mqtt
#	Filename	: solis_config.py
#	Created by	: Andy Taylor

"""Configuration loading for solis2mqtt.

Settings live in a YAML file kept outside git, so the inverter serial and
MQTT password never end up in a tracked (and public) source file.
"""

import os
import sys
import logging

import yaml

# Searched in order; first one that exists wins. Override with SOLIS2MQTT_CONFIG.
CONFIG_PATHS = [
    '/opt/solis2mqtt/config.yaml',
    '/etc/solis2mqtt/config.yaml',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.yaml'),
]

DEFAULTS = {
    'modbus': {
        'host': None,
        'serial': None,
        'port': 8899,
        'slave_id': 1,
        'timeout': 10,
    },
    'mqtt': {
        'host': '127.0.0.1',
        'port': 1883,
        'user': None,
        'password': None,
        'topic': 'emon/solis',
        'keepalive': 60,
        'status_topic': 'solis2mqtt/status',
    },
    'poll_interval': 11,
    'log_level': 'INFO',
}


class ConfigError(Exception):
    """Raised when the config file is missing, unreadable or incomplete."""


def _merge(defaults, override):
    """Recursively overlay override onto a copy of defaults."""
    result = dict(defaults)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def find_config_file():
    """Return the path to the config file, or None if there isn't one."""
    explicit = os.environ.get('SOLIS2MQTT_CONFIG')
    if explicit:
        if not os.path.isfile(explicit):
            raise ConfigError(
                'SOLIS2MQTT_CONFIG points at %s but that file does not exist' % explicit)
        return explicit
    for path in CONFIG_PATHS:
        if os.path.isfile(path):
            return path
    return None


def load(path=None):
    """Load and validate the configuration.

    Raises ConfigError with an actionable message rather than letting a
    KeyError or TypeError surface further down in the poll loop.
    """
    path = path or find_config_file()
    if path is None:
        raise ConfigError(
            'No config file found. Copy config.yaml.example to %s and edit it.'
            % CONFIG_PATHS[0])

    try:
        with open(path, 'r') as handle:
            loaded = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as err:
        raise ConfigError('Unable to read config file %s: %s' % (path, err))

    if loaded is not None and not isinstance(loaded, dict):
        raise ConfigError('Config file %s must contain a YAML mapping' % path)

    config = _merge(DEFAULTS, loaded)
    config['_path'] = path

    # The two settings with no sensible default -- without these we cannot
    # talk to the inverter at all, so fail loudly at startup instead of
    # timing out on every poll.
    if not config['modbus']['host']:
        raise ConfigError('modbus.host is not set in %s' % path)
    if not config['modbus']['serial']:
        raise ConfigError('modbus.serial (the dongle serial number) is not set in %s' % path)

    try:
        config['modbus']['serial'] = int(config['modbus']['serial'])
    except (TypeError, ValueError):
        raise ConfigError('modbus.serial must be a number, got %r'
                          % (config['modbus']['serial'],))

    if config['poll_interval'] <= 0:
        raise ConfigError('poll_interval must be greater than zero')

    return config


def setup_logging(config=None, force_level=None):
    """Configure root logging. systemd captures stderr, so no file handler."""
    level = force_level or (config or {}).get('log_level', 'INFO')
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format='%(levelname)s %(message)s',
        handlers=[logging.StreamHandler(sys.stderr)],
    )
