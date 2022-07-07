# solis2mqtt

Read the registers via Solis' exposed modbus port, using the solarmanv5 protocol  
Push those back to mqtt for logging.


## Requirements / Dependancies

solis2mqtt requires Python 3.8 or greater, it is designed to run on emonPi, but I had to build a  
new image from scratch using the latest Raspbian in order to have the required Python version.  
Please see this excellent guide / documentation here: https://github.com/openenergymonitor/EmonScripts  

Once you have the files downloaded, use your favourite editor and edit the solis2mqtt.py python  
script, you will need to specify the IP address of the Solis WiFi stick AND the Serial nunmber for the  
stick. The Serial number can be found on the Web Dashboard for the stick, the "Device serial number"  
in the "Device information" section.  

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
sudo git clone https://git.always-online.uk/ataylor/Solis2MQTT.git /opt/solis2mqtt
(cd /etc/systemd/system; sudo ln -s /opt/solis2mqtt/solis2mqtt.service ./)
(cd /opt/solis2mqtt; pip3 install -r requirements.txt)
sudo systemctl daemon-reload
sudo systemctl enable solis2mqtt
```


## Setup

Edit (with your favourite editor) /opt/solis2mqtt/solis2mqtt.py and change the following lines to match  
your setup:  

```
MODBUS_SERVER = "1.2.3.4"
MODBUS_DONGLEID = 1234567890
```

The rest of the file is setup to assume this is running on eMonPi already, if not please adjust the  
location for mqtt also. The default passwords for eMonPi mqtt are already in place, if yours  
have been changed, please update those to match your environment too.  

At this point, you should be good to go, start the service, and you should see data arrive in your feeds.  

```
systemctl start solis2mqtt
```


## WiFi Dongle / Timing issues

The dongles appear to get locked from time to time (if this script attempts to get data at the same time  
the stick is due to send the 6 min update to solis cloud for example, it will recover, so if you see the  
last update in your feed count up past the expected 11 secs or so from time to time, yep it does that  
but it will self recover.  

This can also impact how often the stick sends data to the solis cloud, on balance I dont have any isssues  
with that, but if you do, you can adjust the timing some, I find the 11 sec to be a nice balance of working  
well for both local data and remote monitoring in solis cloud. As always, your milage may vary.  

