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
#from datetime import date, datetime, timedelta
from dateutil import tz
from logger import log
#import aioinflux
from goodwe.inverter import OperationMode 

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

# async def listen(mqtt_client):
# #    async with aiomqtt.Client(mqtt_broker_address, mqtt_broker_port, username=mqtt_user, password=mqtt_pwd) as mqtt_client:
#         async with mqtt_client.messages() as messages:
#             await mqtt_client.subscribe(f'goodwe/{goodwe_serial_number}/{control_topic}') #"temperature/#""
#             async for message in messages:
#                 log.debug(message.payload)
#                 # if 'grid_export_limit' in message.payload:
#                 #     requested_grid_export_limit = int(message.payload['grid_export_limit']) #int(message_payload.split(':')[1])
#                 #     log.debug(f'Requested grid export limit: {requested_grid_export_limit}')
#                 # else:
#                 #     log.debug(f'Invalid command action {message.payload}')

# mqtt_client = None

# background_tasks = set()



def get_timezone_aware_local_time():
    """Gets the timezone aware local time."""
    now = datetime.datetime.now()
    timezone = tzlocal.get_localzone()
    local_time = pytz.timezone(str(timezone)).localize(now, is_dst=False)
    return local_time

class Goodwe_MQTT():
    def __init__(self, serial_number, ip_address, mqtt_broker_ip, mqtt_broker_port, mqtt_username, mqtt_password, mqtt_topic_prefix, mqtt_control_topic_postfix, mqtt_runtime_data_topic_postfix,
                 mqtt_grid_export_limit_topic_postfix, delay_between_polls_seconds): # , influxdb_host, influxdb_port, influxdb_database, influxdb_username, influxdb_password, influxdb_measurement
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
        self.operation_mode_topic = f'{mqtt_topic}/operation_mode'

        self.inverter = None
        self.runtime_data = None
        self.operation_mode = None

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
                log.debug(f'send_mqtt_response {self.serial_number} Publishing to {topic}: {payload}')
                await client.publish(topic, payload=json.dumps(payload))
        except Exception as e:
            log.error(f'send_mqtt_response {self.serial_number} MQTT sending error while processing message: {str(e)}')

#        try:
#            # Publish the data to the MQTT broker
#            async with aiomqtt.Client(self.mqtt_broker_ip, self.mqtt_broker_port, username=self.mqtt_username, password=self.mqtt_password) as client:
#                print(f'Publishing {self.serial_number} grid export limit to {self.grid_export_limit_topic}')
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
                        log.info(f'mqtt_client_task {self.serial_number} message: {message}')
                        message_payload = message.payload.decode("utf-8")
                        log.info(f'mqtt_client_task {self.serial_number} message_payload: {message_payload}')

                        if 'get_grid_export_limit' in message_payload:
                            #self.requested_grid_export_limit = int(message_payload['get_grid_export_limit']) #int(message_payload.split(':')[1])
                            # print(f'mqtt_client_task {self.serial_number} Requested grid export limit: {self.requested_grid_export_limit}')
                            log.info(f'mqtt_client_task {self.serial_number} Getting grid export limit from inverter: {message_payload}')
                            self.grid_export_limit = await self.get_grid_export_limit()
                            log.info(f'mqtt_client_task {self.serial_number} Current inverter grid export limit: {self.grid_export_limit}')

                            await self.send_mqtt_export_limit(self.grid_export_limit)

                        elif 'set_grid_export_limit' in message_payload: # test: mosquitto_pub -h localhost -u openhabian -P **** -t goodwe2mqtt/9010KETU21CW3302/control -m '{"set_grid_export_limit":9440}'
                            requested_grid_export_limit_json = json.loads(message_payload)
                            #print(f'mqtt_client_task {self.serial_number} power_json: {requested_grid_export_limit_json}')
                            self.requested_grid_export_limit = int(requested_grid_export_limit_json['set_grid_export_limit'])
                            #print(f'mqtt_client_task {self.serial_number} Requested grid export limit: {self.requested_grid_export_limit}')
                            #power = int(message_payload.split(':')[1])
                            #print(f'mqtt_client_task {self.serial_number} power: {power}')
                            #power = int(message_payload['set_grid_export_limit'])
                            #power2 = message_payload['set_grid_export_limit']
                            
                            #print(f'mqtt_client_task {self.serial_number} power: {power}')
                            #print(f'mqtt_client_task {self.serial_number} power2: {power2}')
                            #self.requested_grid_export_limit = int(message_payload['set_grid_export_limit'])
                            log.info(f'mqtt_client_task {self.serial_number} Setting inverter grid export limit: {message_payload}')
                            await self.set_grid_export_limit(self.requested_grid_export_limit)
                            #await self.set_grid_export_limit(9300)
                            log.debug(f'mqtt_client_task {self.serial_number} Inverter grid export limit set - reading from inverter to check')
                            self.grid_export_limit = await self.get_grid_export_limit()
                            log.info(f'mqtt_client_task {self.serial_number} Current inverter grid export limit: {self.grid_export_limit}')

                            await self.send_mqtt_export_limit(self.grid_export_limit)

                        elif 'get_operation_mode' in message_payload:
                            log.info(f'mqtt_client_task {self.serial_number} Getting operation mode from inverter: {message_payload}')
                            await self.get_operation_mode()

                        elif 'set_eco_discharge' in message_payload:
                            log.info(f'mqtt_client_task {self.serial_number} Setting eco discharge: {message_payload}')
                            if len(message_payload) > 0:
                                # MQTT payload: eco_discharge_power_percent:10
                                try:
                                    requested_eco_discharge_power_percent_json = json.loads(message_payload)
                                    requested_eco_discharge_power_percent = int(requested_eco_discharge_power_percent_json['set_eco_discharge'])           
                                except json.JSONDecodeError:
                                    log.error(f'mqtt_client_task {self.serial_number} Invalid JSON payload: {message_payload}')
                                    continue
                                except KeyError:
                                    log.error(f'mqtt_client_task {self.serial_number} Missing key in JSON payload: {message_payload}')
                                    continue
                                
                                if requested_eco_discharge_power_percent < 0 or requested_eco_discharge_power_percent > 100:
                                    log.error(f'mqtt_client_task {self.serial_number} Invalid eco discharge power percent: {requested_eco_discharge_power_percent}')
                                    continue
                                
                                log.debug(f'mqtt_client_task {self.serial_number} Eco discharge set to: {requested_eco_discharge_power_percent}')

                                operation_mode = OperationMode.ECO_DISCHARGE if requested_eco_discharge_power_percent > 0 else OperationMode.GENERAL
                                await self.inverter.set_operation_mode(operation_mode=operation_mode, eco_mode_power=requested_eco_discharge_power_percent)
                                await self.get_operation_mode()

                        else:
                            log.error(f'mqtt_client_task {self.serial_number} Invalid command action {message_payload}')
            
            
            # Send the result back to the result_topic
            #await client.publish(result_topic, result)
        except Exception as e:
            log.error(f'mqtt_client_task {self.serial_number} Error while processing MQTT message: {str(e)}')

    async def get_grid_export_limit(self):
        self.grid_export_limit = await self.inverter.get_grid_export_limit()
        log.debug(f'get_grid_export_limit {self.serial_number}: Current inverter grid export limit: {self.grid_export_limit}')
        return self.grid_export_limit

    async def set_grid_export_limit(self, requested_grid_export_limit):
        await self.inverter.set_grid_export_limit(requested_grid_export_limit)
        log.debug(f'set_grid_export_limit {self.serial_number}: Grid export limit set: {requested_grid_export_limit}')
        self.requested_grid_export_limit = requested_grid_export_limit
    
    async def get_ongrid_battery_dod(self):
        self.ongrid_battery_dod = await self.inverter.get_ongrid_battery_dod()
        log.debug(f'get_ongrid_battery_dod {self.serial_number} On-grid battery DoD: {self.ongrid_battery_dod}')

    async def get_operation_mode(self):
        log.info(f'mqtt_client_task {self.serial_number} Getting operation mode from inverter...')
        self.operation_mode = await self.inverter.get_operation_mode()
        log.info(f'mqtt_client_task {self.serial_number} Current operation mode: {self.operation_mode}')

        operation_mode_response = {}
        operation_mode_response.update({'operation_mode':self.operation_mode})
        operation_mode_response.update({'serial_number':self.serial_number})
        last_seen = get_timezone_aware_local_time()
        last_seen_string = last_seen.isoformat()
        operation_mode_response.update({'last_seen':last_seen_string})

        await self.send_mqtt_response(self.operation_mode_topic, operation_mode_response)

        return self.operation_mode

    async def read_runtime_data(self):
        start_time = time.time()

        try:
            self.runtime_data = await self.inverter.read_runtime_data()
        except goodwe.exceptions.MaxRetriesException as e:
            log.error(f'read_runtime_data {self.serial_number} Error while reading runtime data: {str(e)}')
            return None
        except goodwe.exceptions.RequestFailedException as e:
            log.error(f'read_runtime_data {self.serial_number} Error while reading runtime data: {str(e)}')
            return None
        except Exception as e:
            log.error(f'read_runtime_data {self.serial_number} Error while reading runtime data: {str(e)}')
            return None
        
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
        #log.debug(f'get_runtime_data {self.serial_number}, processed in {request_processing_time}s, Runtime data: {self.runtime_data}')
        return self.runtime_data

    async def read_device_info(self):
        self.device_info = await self.inverter.read_device_info()
        log.debug(f'read_device_info {self.serial_number} Device info: {self.device_info}')
        return self.device_info

    async def read_storage_info(self):
        self.storage_info = await self.inverter.read_storage_info()
        log.debug(f'read_storage_info {self.serial_number} Storage info: {self.storage_info}')
        return self.storage_info

    async def read_settings_data(self):
        try:
            self.settings = await self.inverter.read_settings_data()
        except goodwe.exceptions.MaxRetriesException as e:
            log.error(f'read_settings_data {self.serial_number} Error while reading inverter settings: {str(e)}')
            return None
        except goodwe.exceptions.RequestFailedException as e:
            log.error(f'read_settings_data {self.serial_number} Error while reading inverter settings: {str(e)}')
            return None
        except Exception as e:
            log.error(f'read_settings_data {self.serial_number} Error while reading inverter settings: {str(e)}')
            return None
        log.debug(f'read_settings_data {self.serial_number} Settings: {self.settings}')
        return self.settings

    async def read_storage_settings(self):
        self.storage_settings = await self.inverter.read_storage_settings()
        log.debug(f'read_storage_settings {self.serial_number} Storage settings: {self.storage_settings}')
        return self.storage_settings

    async def read_grid_settings(self):
        self.grid_settings = await self.inverter.read_grid_settings()
        log.debug(f'read_grid_settings {self.serial_number} Grid settings: {self.grid_settings}')
        return self.grid_settings

    async def read_battery_settings(self):
        self.battery_settings = await self.inverter.read_battery_settings()
        log.debug(f'read_battery_settings {self.serial_number} Battery settings: {self.battery_settings}')
        return self.battery_settings

    async def read_battery_info(self):
        self.battery_info = await self.inverter.read_battery_info()
        log.debug(f'read_battery_info {self.serial_number} Battery info: {self.battery_info}')
        return self.battery_info

    async def read_battery_runtime_data(self):
        self.battery_runtime_data = await self.inverter.read_battery_runtime_data()
        log.debug(f'read_battery_runtime_data {self.serial_number} Battery runtime data: {self.battery_runtime_data}')
        return self.battery_runtime_data

    async def read_battery_soc(self):
        self.battery_soc = await self.inverter.read_battery_soc()
        log.debug(f'read_battery_soc {self.serial_number} Battery SoC: {self.battery_soc}')
        return self.battery_soc

    async def main_loop(self):
        try:
            # Create InfluxDB client
#            influxdb_client = aioinflux.InfluxDBClient(db='mydb', host='localhost', port=8086)

            log.debug(f'main_loop {self.serial_number} started - requesting settings data')
            await self.read_settings_data()
            log.debug(f'main_loop {self.serial_number} settings data received')

            while True:
                log.debug(f'main_loop {self.serial_number} started - awaiting runtime data')
                await self.read_runtime_data()
                log.debug(f'main_loop {self.serial_number} runtime data received')

                try:
                    # Publish the data to the MQTT broker
                    async with aiomqtt.Client(self.mqtt_broker_ip, self.mqtt_broker_port, username=self.mqtt_username, password=self.mqtt_password) as client:
                        log.debug(f'Publishing runtime data to {self.mqtt_runtime_data_topic}')
                        await client.publish(self.mqtt_runtime_data_topic, payload=json.dumps(self.runtime_data))
                except Exception as e:
                    log.error(f'publish_data(): MQTT sending error while processing message: {str(e)}')

                # # Store the data in InfluxDB
                # try:
                #     # Create InfluxDB measurement
                #     measurement = aioinflux.Measurement('my_measurement').tag('serial_number', self.serial_number)

                #     # Add fields to the measurement
                #     for key, value in self.runtime_data.items():
                #         measurement.field(key, value)

                #     # Write the measurement to InfluxDB
                #     await influxdb_client.write(measurement)
                # except Exception as e:
                #     log.error(f'Error while writing data to InfluxDB: {str(e)}')

                await asyncio.sleep(self.delay_between_polls_seconds)
        except KeyboardInterrupt:
            # Disconnect from the MQTT broker
            self.mqtt_task.cancel()
            await self.mqtt_task
            log.error(f'Goodwe_MQTT {self.serial_number} MQTT client disconnected')

async def main(config):

    # start inverter connection and threads
    inverters = []
    log.info(f'Goodwe2MQTT starting with {len(config["goodwe"]["inverters"])} inverters')

    for inverter in config["goodwe"]["inverters"]:
        inv = Goodwe_MQTT(serial_number=inverter["serial_number"], ip_address=inverter["ip_address"], mqtt_broker_ip=config["mqtt"]["broker_ip"], mqtt_broker_port=config["mqtt"]["broker_port"],
                          mqtt_username=config["mqtt"]["username"], mqtt_password=config["mqtt"]["password"],
                          mqtt_topic_prefix=config["mqtt"]["topic_prefix"], mqtt_control_topic_postfix=config["mqtt"]["control_topic_postfix"], mqtt_runtime_data_topic_postfix=config["mqtt"]["runtime_data_topic_postfix"],
                          mqtt_grid_export_limit_topic_postfix=config["mqtt"]["grid_export_limit_topic_postfix"], delay_between_polls_seconds=config["goodwe"]["poll_interval"])

        await inv.connect_inverter() # start inverter connection and threads
        inverters.append(inv)
        asyncio.ensure_future(inverters[-1].main_loop())

        # wait between starting threads to distribute the communication load in time
        await asyncio.sleep(config["goodwe"]["poll_interval"] / 2.0)

    await asyncio.gather(*[inv.mqtt_task for inv in inverters]) 

# Function to read the configuration from the YAML file
def read_config(file_path):
    # read config from yaml file
    try:
        config = yaml.load(open(file_path), Loader=yaml.FullLoader)
    except Exception as e:
        log.error(f'Error loading YAML file "{file_path}": {e}')
        sys.exit()
    
    return config
    # with open(file_path, "r") as f:
    #     config = yaml.safe_load(f)
    # return config

if __name__ == '__main__':

    # Read the configuration from the YAML file
    config = read_config(config_file)

    # Start the main loop
    asyncio.run(main(config))
    


