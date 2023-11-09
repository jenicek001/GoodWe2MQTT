#!/usr/bin/env python
import minimalmodbus
import serial
import time
import yaml # pip install PyYAML
import sys
import json
import paho.mqtt.client as mqtt
from datetime import date, datetime, timedelta
from dateutil import tz
from logger import log

class EM340:
    def __init__(self, config_file):
        try:
            self.em340_config = yaml.load(open(config_file), Loader=yaml.FullLoader)
        except Exception as e:
            log.error(f'Error loading YAML file: {e}')
            sys.exit()

        self.device = self.em340_config['config']['device']
        self.modbus_address = self.em340_config['config']['modbus_address']
        self.t_delay_seconds = self.em340_config['config']['t_delay_ms'] / 1000.0

        self.em340 = minimalmodbus.Instrument(self.device, self.modbus_address) # port name, slave address (in decimal)
        self.em340.serial.port # this is the serial port name
        self.em340.serial.baudrate = 9600 # Baud
        self.em340.serial.bytesize = 8
        self.em340.serial.parity = serial.PARITY_NONE
        self.em340.serial.stopbits = 1
        #self.em340.serial.timeout = 0.05 # seconds
        self.em340.serial.timeout = 0.5 # seconds
        self.em340.mode = minimalmodbus.MODE_RTU # rtu or ascii mode

        # MQTT client setup
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.username_pw_set(self.em340_config['mqtt']['username'], self.em340_config['mqtt']['password'])
        self.mqtt_client.connect(self.em340_config['mqtt']['broker'], self.em340_config['mqtt']['port'])
        self.topic = self.em340_config['mqtt']['topic'] + '/' + self.em340_config['config']['name']

    def read_sensors(self):
        while True:
            log.debug('Reading EM340...')
            data = {}
            for register in self.em340_config['sensor']:
                #log.info(f"Reading {register['name']} at register {register['address']}")
                ## Read value from EM340
                try:
                    #temperature = self.em340.read_register(288, 10) # Registernumber, number of decimals
                    #temperature = self.em340.read_register(0x0000, 20) # Registernumber, number of decimals
                    #value = self.em340.read_register(register['address'], register['accuracy_decimals']) # Registernumber, number of decimals
                    if register['skip'] == True:
                        continue

                    signed = register['value_type'] == "INT16" or register['value_type'] == "INT32"
                    value = self.em340.read_register(register['address'], signed=signed) # Registernumber, number of decimals
                    if value is None:
                        raise ValueError(f"Missing value for register {register['name']} at address {register['address']}")
                    #log.info(value)
                    #value = value / 10**register['accuracy_decimals']
                    #log.info(register['filters'])
                    #log.info(register['filters'][0])
                    #log.info(register['filters'][0]['multiply'])
                    #log.info(float(register['filters'][0]['multiply']))
                    value = value * float(register['multiply'])
                    units = register['unit_of_measurement'] if 'unit_of_measurement' in register else ''
                    log.debug(f'{register["name"]} {value} {units}')
                    data[register['id']] = value
                    time.sleep(self.t_delay_seconds)
                except IOError as err:
                    log.error(f'Failed to read from ModBus device at {self.em340.serial.port}: {err}')
                except ValueError as err:
                    log.error(f'Error reading register: {err}')
                    time.sleep(self.t_delay_seconds)
                except KeyError as err:
                    log.error(f'Error in yaml config file: {err}')
                    sys.exit()
                except KeyboardInterrupt:
                    log.error("Keyboard interrupt detected. Exiting...")
                    sys.exit()

            # Add timestamp in local time as last_seen


            data['last_seen'] = datetime.now(tz=tz.tzlocal()).isoformat()

            # Publish data to MQTT topic
            payload = json.dumps(data)
            self.mqtt_client.publish(self.topic, payload)

if __name__ == '__main__':
    log.info('Starting EM340d...')
    em340 = EM340('em340.yaml')
    em340.read_sensors()
