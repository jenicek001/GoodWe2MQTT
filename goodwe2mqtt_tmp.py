import asyncio
import aiomqtt # https://sbtinstruments.github.io/aiomqtt/publishing-a-message.html
import goodwe
import time
import datetime
import pytz
import tzlocal
import json
import paho.mqtt.client as mqtt
import yaml # pip install PyYAML
import sys
import json
from datetime import date, datetime, timedelta
from dateutil import tz
from logger import log

config_file = "goodwe2mqtt.yaml"

# this function dumps runtime_data to JSON file, filename contains date and time
def dump_to_json(runtime_data):
    # dump dictionary to file
    current_time = datetime.datetime.now()
    inverter_runtime_data_json = json.dumps(runtime_data)
    log.debug(f'JSON: {inverter_runtime_data_json}')

    # directory name for current config generation YYYY-MM-DD_HH-MM-SS
    file_name = current_time.strftime("data/pv_inverter_status-%Y-%m-%d_%H-%M-%S.json")
    with open(file_name, 'w') as outfile:
        json.dump(runtime_data, outfile)

def get_timezone_aware_local_time():
    """Gets the timezone aware local time."""
    now = datetime.datetime.now()
    timezone = tzlocal.get_localzone()
    local_time = pytz.timezone(str(timezone)).localize(now, is_dst=False)
    return local_time

class GoodWe_Thread():
    def __init__(self, serial_number, ip_address, mqtt_broker_ip, mqtt_broker_port, mqtt_username, mqtt_password, mqtt_topic_prefix, mqtt_control_topic_postfix, mqtt_runtime_data_topic_postfix, mqtt_grid_export_limit_topic_postfix, delay_between_polls_seconds):
        self.serial_number = serial_number
        self.ip_address = ip_address

        self.mqtt_broker_ip = mqtt_broker_ip
        self.mqtt_broker_port = mqtt_broker_port
        self.mqtt_username = mqtt_username
        self.mqtt_password = mqtt_password
        self.delay_between_polls_seconds = delay_between_polls_seconds

        self.grid_export_limit = None
        self.requested_grid_export_limit = None

        mqtt_topic = f'{mqtt_topic_prefix}/{self.serial_number}'
        self.mqtt_control_topic = f'{mqtt_topic}/{mqtt_control_topic_postfix}'
        self.mqtt_runtime_data_topic = f'{mqtt_topic}/{mqtt_runtime_data_topic_postfix}'
        self.grid_export_limit_topic = f'{mqtt_topic}/{mqtt_grid_export_limit_topic_postfix}'

        self.inverter = None
        self.runtime_data = None

        log.info(self)

        self.mqtt_task = asyncio.ensure_future(self.mqtt_client_task())

    def __str__(self):
        return f'{self.serial_number}, {self.ip_address}, {self.grid_export_limit}, {self.mqtt_broker_ip}, {self.mqtt_broker_port}, {self.mqtt_username}, {"****"}, {self.mqtt_control_topic}, {self.mqtt_runtime_data_topic}, {self.grid_export_limit_topic}, {self.delay_between_polls_seconds}'

    async def connect_inverter(self):
        log.info(f'Connecting to inverter {self.serial_number} at {self.ip_address}')
        start_time = time.time()
        self.inverter = await goodwe.connect(host = self.ip_address, family = 'ET')
        connection_time = time.time() - start_time
        log.info(f'Connected to inverter {self.serial_number} in {connection_time} seconds')
        return self.inverter

    async def send_mqtt_export_limit(self, grid_export_limit):
        grid_export_limit_response = {}
        grid_export_limit_response.update({'grid_export_limit':grid_export_limit})
        grid_export_limit_response.update({'serial_number':self.serial_number})
        last_seen = get_timezone_aware_local_time()
        last_seen_string = last_seen.isoformat()
        grid_export_limit_response.update({'last_seen':last_seen_string})

        await self.send_mqtt_response(self.grid_export_limit_topic, grid_export_limit_response)

    async def send_mqtt_response(self, topic, payload):
        try:
            async with aiomqtt.Client(self.mqtt_broker_ip, self.mqtt_broker_port, username=self.mqtt_username, password=self.mqtt_password) as client:
                log.info(f'send_mqtt_response {self.serial_number} Publishing to {topic}: {payload}')
                await client.publish(topic, payload=json.dumps(payload))
        except Exception as e:
            log.error(f'send_mqtt_response {self.serial_number} MQTT sending error while processing message: {str(e)}')

#        try:
#            # Publish the data to the MQTT broker
#            async with aiomqtt.Client(self.mqtt_broker_ip, self.mqtt_broker_port, username=self.mqtt_username, password=self.mqtt_password) as client:
#                log.error(f'Publishing {self.serial_number} grid export limit to {self.grid_export_limit_topic}')
#                await client.publish(self.grid_export_limit_topic, payload=json.dumps(grid_export_limit_response))
#        except Exception as e:
#            log.error(f'publish_data(): MQTT sending error while processing message: {str(e)}')


    async def mqtt_client_task(self):
        log.debug(f'mqtt_client_task: {self.serial_number}')

        try:
            async with aiomqtt.Client(self.mqtt_broker_ip, self.mqtt_broker_port, username=self.mqtt_username, password=self.mqtt_password) as client:
                log.info(f'mqtt_client_task {self.serial_number} connected to MQTT broker {self.mqtt_broker_ip}:{self.mqtt_broker_port}')
                async with client.messages() as messages:
                    await client.subscribe(self.mqtt_control_topic)
                    async for message in messages:
                        log.debug(f'mqtt_client_task {self.serial_number} message: {message}')
                        message_payload = message.payload.decode("utf-8")
                        log.debug(f'mqtt_client_task {self.serial_number} message_payload: {message_payload}')

                        if 'get_grid_export_limit' in message_payload:
                            #self.requested_grid_export_limit = int(message_payload['get_grid_export_limit']) #int(message_payload.split(':')[1])
                            # log.debug(f'mqtt_client_task {self.serial_number} Requested grid export limit: {self.requested_grid_export_limit}')
                            log.info(f'mqtt_client_task {self.serial_number} Getting grid export limit from inverter: {message_payload}')
                            self.grid_export_limit = await self.get_grid_export_limit()
                            log.info(f'mqtt_client_task {self.serial_number} Current inverter grid export limit: {self.grid_export_limit}')

                            await self.send_mqtt_export_limit(self.grid_export_limit)

                        elif 'set_grid_export_limit' in message_payload: # test: mosquitto_pub -h localhost -u openhabian -P **** -t goodwe2mqtt/9010KETU21CW3302/control -m '{"set_grid_export_limit":9440}'
                            requested_grid_export_limit_json = json.loads(message_payload)
                            #log.debug(f'mqtt_client_task {self.serial_number} power_json: {requested_grid_export_limit_json}')
                            self.requested_grid_export_limit = int(requested_grid_export_limit_json['set_grid_export_limit'])
                            #log.debug(f'mqtt_client_task {self.serial_number} Requested grid export limit: {self.requested_grid_export_limit}')
                            #power = int(message_payload.split(':')[1])
                            #log.debug(f'mqtt_client_task {self.serial_number} power: {power}')
                            #power = int(message_payload['set_grid_export_limit'])
                            #power2 = message_payload['set_grid_export_limit']
                            
                            #log.debug(f'mqtt_client_task {self.serial_number} power: {power}')
                            #log.debug(f'mqtt_client_task {self.serial_number} power2: {power2}')
                            #self.requested_grid_export_limit = int(message_payload['set_grid_export_limit'])
                            log.info(f'mqtt_client_task {self.serial_number} Setting inverter grid export limit: {message_payload}')
                            await self.set_grid_export_limit(self.requested_grid_export_limit)
                            #await self.set_grid_export_limit(9300)
                            log.info(f'mqtt_client_task {self.serial_number} Inverter grid export limit set - reading from inverter to check')
                            self.grid_export_limit = await self.get_grid_export_limit()
                            log.info(f'mqtt_client_task {self.serial_number} Current inverter grid export limit: {self.grid_export_limit}')

                            await self.send_mqtt_export_limit(self.grid_export_limit)

                        else:
                            log.error(f'mqtt_client_task {self.serial_number} Invalid command action {message_payload}')
            
            
            # Send the result back to the result_topic
            #await client.publish(result_topic, result)
        except Exception as e:
            log.error(f'mqtt_client_task {self.serial_number} Error while processing MQTT message: {str(e)}')

    async def get_grid_export_limit(self):
        self.grid_export_limit = await self.inverter.get_grid_export_limit()
        log.info(f'get_grid_export_limit {self.serial_number}: Current inverter grid export limit: {self.grid_export_limit}')
        return self.grid_export_limit
    
    async def get_operation_mode(self):
        self.operation_mode = await self.inverter.get_operation_mode()
        log.info(f'get_oiperation_mode {self.serial_number} Operation mode: {self.operation_mode}')
        return self.operation_mode

    async def set_grid_export_limit(self, requested_grid_export_limit):
        await self.inverter.set_grid_export_limit(requested_grid_export_limit)
        log.info(f'set_grid_export_limit {self.serial_number}: Grid export limit set: {requested_grid_export_limit}')
        self.requested_grid_export_limit = requested_grid_export_limit
    
    async def get_ongrid_battery_dod(self):
        self.ongrid_battery_dod = await self.inverter.get_ongrid_battery_dod()
        log.info(f'get_ongrid_battery_dod {self.serial_number} On-grid battery DoD: {self.ongrid_battery_dod}')

    async def read_runtime_data(self):
        start_time = time.time()

        # TODO: add try/except
        self.runtime_data = await self.inverter.read_runtime_data()
        
        # replace goodwe lib inverter timestamp with iso string
        inverter_timestamp = self.runtime_data['timestamp']
        inverter_timestamp_string = inverter_timestamp.isoformat()

        self.runtime_data.update({'timestamp':inverter_timestamp_string})
        request_processing_time = time.time() - start_time
        self.runtime_data.update({'serial_number':self.serial_number})
        last_seen = get_timezone_aware_local_time()
        last_seen_string = last_seen.isoformat()
        self.runtime_data.update({'last_seen':last_seen_string})
        self.runtime_data.update({'request_processing_time':request_processing_time})
        #log.info(f'get_runtime_data {self.serial_number}, processed in {request_processing_time}s, Runtime data: {self.runtime_data}')
        return self.runtime_data

    async def read_device_info(self):
        self.device_info = await self.inverter.read_device_info()
        log.info(f'read_device_info {self.serial_number} Device info: {self.device_info}')
        return self.device_info

    async def read_storage_info(self):
        self.storage_info = await self.inverter.read_storage_info()
        log.info(f'read_storage_info {self.serial_number} Storage info: {self.storage_info}')
        return self.storage_info

    async def read_settings(self):
        self.settings = await self.inverter.read_settings()
        log.info(f'read_settings {self.serial_number} Settings: {self.settings}')
        return self.settings

    async def read_storage_settings(self):
        self.storage_settings = await self.inverter.read_storage_settings()
        log.info(f'read_storage_settings {self.serial_number} Storage settings: {self.storage_settings}')
        return self.storage_settings

    async def read_grid_settings(self):
        self.grid_settings = await self.inverter.read_grid_settings()
        log.info(f'read_grid_settings {self.serial_number} Grid settings: {self.grid_settings}')
        return self.grid_settings

    async def read_battery_settings(self):
        self.battery_settings = await self.inverter.read_battery_settings()
        log.info(f'read_battery_settings {self.serial_number} Battery settings: {self.battery_settings}')
        return self.battery_settings

    async def read_battery_info(self):
        self.battery_info = await self.inverter.read_battery_info()
        log.info(f'read_battery_info {self.serial_number} Battery info: {self.battery_info}')
        return self.battery_info

    async def read_battery_runtime_data(self):
        self.battery_runtime_data = await self.inverter.read_battery_runtime_data()
        log.info(f'read_battery_runtime_data {self.serial_number} Battery runtime data: {self.battery_runtime_data}')
        return self.battery_runtime_data

    async def read_battery_soc(self):
        self.battery_soc = await self.inverter.read_battery_soc()
        log.info(f'read_battery_soc {self.serial_number} Battery SoC: {self.battery_soc}')
        return self.battery_soc

    async def main_loop(self):
        try:
            while True:
                log.debug(f'main_loop {self.serial_number} started - awaiting runtime data')
                await self.read_runtime_data()
                log.debug(f'main_loop {self.serial_number} runtime data received')
        #        log.debug(f'Runtime data from inverter: {runtime_data}')
                # dump_to_json(runtime_data)

                try:
                    # Publish the data to the MQTT broker
                    async with aiomqtt.Client(self.mqtt_broker_ip, self.mqtt_broker_port, username=self.mqtt_username, password=self.mqtt_password) as client:
                        log.debug(f'Publishing runtime data to {self.mqtt_runtime_data_topic}')
                        await client.publish(self.mqtt_runtime_data_topic, payload=json.dumps(self.runtime_data))
                except Exception as e:
                    log.error(f'publish_data(): MQTT sending error while processing message: {str(e)}')

                # if current_grid_export_limit != requested_grid_export_limit:
                #     await inverter.set_grid_export_limit(requested_grid_export_limit)
                #     log.error(f'Grid export limit set: {requested_grid_export_limit}')
                #     current_grid_export_limit = await inverter.get_grid_export_limit()
                #     log.error(f'Current inverter grid export limit: {current_grid_export_limit}')

                await asyncio.sleep(self.delay_between_polls_seconds)
        except KeyboardInterrupt:
            # Disconnect from the MQTT broker
            self.mqtt_task.cancel()
            await self.mqtt_task
            log.error(f'Goodwe_MQTT {self.serial_number} MQTT client disconnected')

async def main(config_file):

    # read config from yaml file
    try:
        config = yaml.load(open(config_file), Loader=yaml.FullLoader)
    except Exception as e:
        log.error(f'Error loading YAML file "{config_file}": {e}')
        sys.exit()
    
    # start inverter connection and threads
    inverters = []

    for inverter in config["goodwe"]["inverters"]:
        inv = GoodWe_Thread(serial_number=inverter["serial_number"], ip_address=inverter["ip_address"], mqtt_broker_ip=config["mqtt"]["broker_ip"], mqtt_broker_port=config["mqtt"]["broker_port"],
                          mqtt_username=config["mqtt"]["username"], mqtt_password=config["mqtt"]["password"],
                          mqtt_topic_prefix=config["mqtt"]["topic_prefix"], mqtt_control_topic_postfix=config["mqtt"]["control_topic_postfix"], mqtt_runtime_data_topic_postfix=config["mqtt"]["runtime_data_topic_postfix"],
                          mqtt_grid_export_limit_topic_postfix=config["mqtt"]["grid_export_limit_topic_postfix"], delay_between_polls_seconds=config["goodwe"]["poll_interval"])

        await inv.connect_inverter() # start inverter connection and threads
        inverters.append(inv)
        asyncio.ensure_future(inverters[-1].main_loop())


    # Start the main loop
    asyncio.run(main(config))


        # wait between starting threads to distribute the communication load in time
        await asyncio.sleep(config["goodwe"]["poll_interval"] / 2.0)

    await asyncio.gather(*[inv.mqtt_task for inv in inverters]) 

# Function to read the configuration from the YAML file
def read_config(file_path):
    with open(file_path, "r") as f:
        config = yaml.safe_load(f)
    return config

if __name__ == '__main__':

    # Read the configuration from the YAML file
    config = read_config(config_file)

    # Start the main loop
    asyncio.run(main(config))

def main():


if __name__ == '__main__':
    log.info('Starting GoodWe2MQTT...')
    main()





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

