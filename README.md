# solis2mqtt

Read the registers via Solis' exposed modbus port, using the solarmanv5 protocol  
Push those back to mqtt for logging.


## Requirements / Dependancies

solis2mqtt requires Python 3.8 or greater, it is designed to run on emonPi. If your emonPi image is  
older than Python 3.8 you will need to build a new image; please see this excellent guide /  
documentation here: https://github.com/openenergymonitor/EmonScripts  

Check your python3 version with  

```
python3 --version
```

if you do not have 3.8 or later, the required module "pysolamanv5" will not work, and you will not get  
data from the Solis Inverter.  

solis2mqtt would not be possible without the excellent work by other people, jmccrohan, thank you, see  
his "pysolarmanv5" module here: https://github.com/jmccrohan/pysolarmanv5  


## Installation

```
sudo git clone https://github.com/AndyTaylorTweet/solis2mqtt.git /opt/solis2mqtt
sudo /opt/solis2mqtt/install.sh
```

`install.sh` creates a virtualenv in `/opt/solis2mqtt/.venv`, installs the dependencies into it,  
copies `config.yaml.example` to `config.yaml`, and links and enables the systemd unit. It is safe  
to re-run; it will never overwrite an existing `config.yaml`.  

The virtualenv is not optional on current Raspberry Pi OS. Debian 12 and later mark the system  
Python as externally managed (PEP 668), so a plain `pip3 install` into it is refused.  


## Setup

Copy `/opt/solis2mqtt/config.yaml.example` to `/opt/solis2mqtt/config.yaml` and edit it with the  
details from your inverter. If you ran `install.sh` the copy is already there, and `cp -n` below  
will leave it alone.  

```
sudo cp -n /opt/solis2mqtt/config.yaml.example /opt/solis2mqtt/config.yaml
sudo chown pi:pi /opt/solis2mqtt/config.yaml
sudo chmod 600 /opt/solis2mqtt/config.yaml
sudo nano /opt/solis2mqtt/config.yaml
```

Set the address and serial number of your Solis WiFi stick:  

```yaml
modbus:
  host: 192.168.0.10
  serial: 1234567890
```

The serial number can be found on the Web Dashboard for the stick, the "Device serial number" in  
the "Device information" section.  

The rest of the file assumes this is running on an emonPi, with the stock emonPi mqtt credentials  
already in place. If yours have been changed, or mqtt lives elsewhere, adjust the `mqtt` section  
to match. See `config.yaml.example` for what every setting does.  

`config.yaml` is not tracked in git, so your settings survive an upgrade and your mqtt password is  
never committed.  

Start the service and you should see data arrive in your feeds:  

```
sudo systemctl start solis2mqtt
journalctl -u solis2mqtt -f
```


## Upgrading

```
sudo git -C /opt/solis2mqtt pull
sudo /opt/solis2mqtt/install.sh
sudo systemctl restart solis2mqtt
```

Re-running `install.sh` picks up any new dependencies and reloads the unit. Your `config.yaml` is  
left alone.  


## Published topics

Everything is published under the configured base topic, `emon/solis` by default, so emoncms picks  
the readings up as inputs on a node called `solis`.  

| Topic | Unit | Notes |
| --- | --- | --- |
| `pv_voltage` / `pv_current` | V / A | PV string 1 |
| `pv2_voltage` / `pv2_current` | V / A | PV string 2 |
| `pv_power` | W | Total DC power reported by the inverter |
| `pv_string_power` | W | Derived: V×A summed across both strings |
| `inv_power` | W | Inverter output, signed |
| `inv_load` | W | House load |
| `grid_power` | W | Signed; negative is export |
| `battery_soc` | % | |
| `battery_voltage` / `battery_current` | V / A | |
| `battery_power` | W | Unsigned magnitude |
| `battery_charge` / `battery_discharge` | W | The inactive one reads 0 |
| `battery_power_signed` | W | Positive charging, negative discharging |
| `battery_soh` | % | Battery state of health |
| `grid_voltage` | V | Measured at the inverter |
| `grid_frequency` | Hz | |
| `sys_temp` | °C | Inverter temperature |
| `energy_today` / `energy_yesterday` | kWh | |
| `energy_this_month` / `energy_last_month` | kWh | |
| `energy_this_year` / `energy_last_year` | kWh | |
| `energy_total` | kWh | Lifetime generation |

The energy counters come from the inverter's own totals rather than being integrated from  
`pv_power`, so they do not drift and they survive an outage of this service.  

A retained `solis2mqtt/status` topic carries `online` / `offline`, with `offline` also set as the  
MQTT last will so an unclean exit is visible. It sits outside the `emon/` tree deliberately, so  
emoncms does not create an input for it.  

Readings that fall outside a plausible range for that metric are dropped with a warning rather than  
published, so a garbled read cannot poison a feed.  

Everything is published so you can pick what to keep. Log to a feed only what you actually want  
graphed; the rest are still there to look at live on the Inputs page. What I log:  

| Input | Feed |
| --- | --- |
| `pv_power` | power, and kWh |
| `inv_power` | power, and kWh |
| `grid_power` | power, kWh, and split into import and export |
| `battery_soc` | level |
| `battery_power` | power |
| `battery_charge` / `battery_discharge` | power, and kWh each |

Feeds only start from the moment you add the processing, so there is no backfill.  


## Switching the inverter on and off

```
/opt/solis2mqtt/.venv/bin/python /opt/solis2mqtt/solisctl.py off
/opt/solis2mqtt/.venv/bin/python /opt/solis2mqtt/solisctl.py on
```

`solisOn.py` and `solisOff.py` are wrappers around the same code. Run interactively they ask for  
confirmation first; pass `-y`, or run them from a script or cron where stdin is not a terminal, to  
skip the prompt.  


## WiFi Dongle / Timing issues

The dongles appear to get locked from time to time (if this script attempts to get data at the same time  
the stick is due to send the 6 min update to solis cloud for example), it will recover, so if you see the  
last update in your feed count up past the expected 11 secs or so from time to time, yep it does that  
but it will self recover.  

To keep this to a minimum, each poll reads two contiguous register blocks rather than one request  
per value, so there are only two round trips to the dongle. A failed read is retried once on a  
fresh connection before the poll is abandoned.  

This can also impact how often the stick sends data to the solis cloud, on balance I dont have any isssues  
with that, but if you do, you can adjust `poll_interval` in the config. I find the 11 sec to be a nice  
balance of working well for both local data and remote monitoring in solis cloud. As always, your  
milage may vary.  

If polls fail 20 times in a row the service exits so systemd restarts it with a clean slate.  


## Supported inverters

At startup the inverter is asked for register 35000, which Solis define as its type: the high byte  
is the protocol it speaks, the low byte the model. This service reads the energy storage protocol  
(`ESINV-33000ID`, protocol `0x20`), so it refuses to start against a string inverter, which speaks  
`0x10` and puts completely different things at these addresses. Better to say so than to fill your  
feeds with nonsense.  

Verified against `0x2030`, a 1 phase low voltage energy storage inverter. Other energy storage  
models (`0x31`, `0x40`, `0x50`, `0x60`) will start, with a warning that the map has not been checked  
against them. If you run one, readings that look wrong are worth reporting.  

The model and serial number are logged at startup:  

```
INFO Inverter: 1 phase low voltage energy storage, energy storage (ESINV-33000ID) protocol (0x2030), serial 160F5221C1601830
```


## Adding registers

The register map lives in `solis.py` as a list of blocks, each with a start address, a length and  
the registers decoded from it. To add a value, add a `Register(...)` to whichever block already  
covers its address:  

```python
Register('battery_soh', 33140, 1, 1, unit='%', sane=(0, 100))
```

The inverter accepts at most 100 registers in a single request. Ask for 101 and it answers  
`IllegalDataAddressError`, which is misleading: the addresses are fine, the count is not.  

The registers you want do not need to be adjacent. A request spanning unused registers costs the  
same as one that does not, so it is nearly always cheaper to read a wide block and ignore the gaps  
than to issue a request per value. There are two blocks here only because `battery_power` sits at  
33149, and reaching it from 33049 would need 102 registers.  
