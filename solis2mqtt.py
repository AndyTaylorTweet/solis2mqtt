#!/usr/bin/env python3

#	Project		: solis2mqtt
#	Filename	: solis2mqtt.py
#	Created by	: Andy Taylor
#	Created on	: 10/05/2022

"""Poll a Solis inverter over modbus and republish the readings to MQTT."""

import logging
import signal
import sys
import time

import paho.mqtt.client as mqtt

import solis_config as config_module
import solis

log = logging.getLogger('solis2mqtt')

# Give up and let systemd restart us with a clean slate after this many
# consecutive failed polls. The dongle usually recovers well before this.
MAX_CONSECUTIVE_FAILURES = 20


PAHO_V2 = hasattr(mqtt, 'CallbackAPIVersion')


def make_mqtt_client(client_id):
    """Build a paho client, working with both paho-mqtt 1.x and 2.x."""
    if PAHO_V2:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    return mqtt.Client(client_id=client_id)


def failed(reason_code):
    """Did a callback report a failure?

    paho 1.x hands callbacks a plain integer, 2.x a ReasonCode object.
    """
    if reason_code is None:
        return False
    return bool(getattr(reason_code, 'is_failure', reason_code != 0))


class Publisher:
    """A single long-lived MQTT connection.

    The old version connected and disconnected around every publish. paho
    reconnects on its own from the network loop thread, so one connection
    held open for the life of the process is both simpler and far less
    chatty against the broker.
    """

    def __init__(self, settings):
        self.settings = settings
        self.topic = settings['topic'].rstrip('/')
        self.status_topic = settings.get('status_topic')
        self.client = make_mqtt_client('solis2mqtt')
        if settings.get('user'):
            self.client.username_pw_set(settings['user'], settings.get('password'))
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.reconnect_delay_set(min_delay=1, max_delay=60)
        if self.status_topic:
            self.client.will_set(self.status_topic, 'offline', retain=True)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if failed(reason_code):
            log.error('MQTT connection refused: %s', reason_code)
            return
        log.info('Connected to MQTT broker at %s:%s',
                 self.settings['host'], self.settings['port'])
        if self.status_topic:
            client.publish(self.status_topic, 'online', retain=True)

    def _on_disconnect(self, client, userdata, *args):
        # 1.x passes (rc,); 2.x passes (disconnect_flags, reason_code, properties).
        reason_code = args[1] if len(args) >= 2 else args[0]
        if failed(reason_code):
            log.warning('Disconnected from MQTT broker (%s), will retry', reason_code)

    def start(self):
        self.client.connect_async(
            self.settings['host'], self.settings['port'], self.settings['keepalive'])
        self.client.loop_start()

    def stop(self):
        if self.status_topic:
            self.client.publish(self.status_topic, 'offline', retain=True)
            time.sleep(0.2)  # Let the final publish leave before we tear down.
        self.client.loop_stop()
        self.client.disconnect()

    def publish(self, readings):
        """Publish each reading as its own topic under the base topic."""
        for name in sorted(readings):
            self.client.publish('%s/%s' % (self.topic, name), str(readings[name]))


class Service:

    def __init__(self, cfg):
        self.cfg = cfg
        self.inverter = solis.Inverter(
            cfg['modbus']['host'], cfg['modbus']['serial'],
            port=cfg['modbus']['port'], slave_id=cfg['modbus']['slave_id'],
            timeout=cfg['modbus']['timeout'],
        )
        self.publisher = Publisher(cfg['mqtt'])
        self.running = True
        self.failures = 0

    def shutdown(self, signum, frame):
        log.info('Received signal %s, shutting down', signum)
        self.running = False

    def poll_once(self):
        try:
            readings = self.inverter.read_all()
        except solis.TransientError as err:
            self.failures += 1
            log.warning('Poll failed (%s consecutive): %s', self.failures, err)
            return
        except Exception as err:
            self.failures += 1
            log.exception('Unexpected error reading inverter (%s consecutive): %s',
                          self.failures, err)
            self.inverter.disconnect()
            return

        if self.failures:
            log.info('Inverter recovered after %s failed poll(s)', self.failures)
        self.failures = 0
        self.publisher.publish(readings)
        log.debug('Published %s readings', len(readings))

    def run(self):
        signal.signal(signal.SIGTERM, self.shutdown)
        signal.signal(signal.SIGINT, self.shutdown)

        self.publisher.start()
        interval = self.cfg['poll_interval']
        log.info('Polling %s every %ss, publishing to %s/',
                 self.cfg['modbus']['host'], interval, self.cfg['mqtt']['topic'])

        # Schedule against a monotonic clock so a slow read does not make
        # the interval drift out over time.
        next_poll = time.monotonic()
        while self.running:
            self.poll_once()

            if self.failures >= MAX_CONSECUTIVE_FAILURES:
                log.error('%s consecutive failures, exiting for a clean restart',
                          self.failures)
                self.publisher.stop()
                return 1

            next_poll += interval
            sleep_for = next_poll - time.monotonic()
            if sleep_for < 0:
                # Reads took longer than the interval; resync rather than
                # trying to catch up on missed polls.
                next_poll = time.monotonic()
                sleep_for = 0
            # Wake up regularly so a signal is acted on promptly.
            while sleep_for > 0 and self.running:
                time.sleep(min(sleep_for, 1.0))
                sleep_for -= 1.0

        self.publisher.stop()
        log.info('Stopped')
        return 0


def main():
    try:
        cfg = config_module.load()
    except config_module.ConfigError as err:
        config_module.setup_logging(force_level='INFO')
        log.error('%s', err)
        return 2

    config_module.setup_logging(cfg)
    log.info('Using config %s', cfg['_path'])
    return Service(cfg).run()


if __name__ == '__main__':
    sys.exit(main())
