#!/usr/bin/env python3

# from collections import namedtuple
# from sys import stdout

import requests
import json

from serial.serialutil import SerialException
# import serial.tools.list_ports
import serial
import time
from time import sleep
import subprocess
import crcmod
import os

import argparse

from enum import Enum, auto

from types import SimpleNamespace

from helpers import send_request

PROVISIONING_SKETCH_RESPONSE = [0x55, 0xaa, 0x01, 0x01, 0xff, 0xaa, 0x55]
MAX_SERIAL_BUFFER = 128
MIN_MESSAGE_LENGTH = 10

_CRC_FUNC = crcmod.mkCrcFun(0x11021, initCrc=0, xorOut=0xffff)

CRC16_SIZE = 2
msg_start = [0x55, 0xaa]
msg_end = [0xaa, 0x55]

deviceCSR = []
device_id = ""

# MESSAGES


class MESSAGE_TYPE(Enum):
    NONE = 0
    COMMAND = auto()
    DATA = auto()
    RESPONSE = auto()


# COMMANDS

class COMMAND(Enum):
    GET_SKETCH_INFO = 1
    GET_CSR = auto()
    SET_LOCKED = auto()
    GET_LOCKED = auto()
    WRITE_CRYPTO = auto()
    BEGIN_STORAGE = auto()
    SET_DEVICE_ID = auto()
    SET_YEAR = auto()
    SET_MONTH = auto()
    SET_DAY = auto()
    SET_HOUR = auto()
    SET_VALIDITY = auto()
    SET_CERT_SERIAL = auto()
    SET_AUTH_KEY = auto()
    SET_SIGNATURE = auto()
    END_STORAGE = auto()
    RECONSTRUCT_CERT = auto()


# ERRORS

class ERROR(Enum):
    NONE = 0
    SYNC = auto()
    LOCK_FAIL = auto()
    LOCK_SUCCESS = auto()
    WRITE_CONFIG_FAIL = auto()
    CRC_FAIL = auto()
    CSR_GEN_FAIL = auto()
    CSR_GEN_SUCCESS = auto()
    SKETCH_UNKNOWN = auto()
    GENERIC = auto()
    ERROR_NO_DATA = auto()


# Python to Board FUNCTIONS

def compose_message(msg_type, msg_payload):
    formed_message = bytearray(msg_start)
    formed_message.append(msg_type)
    payload_size = len(msg_payload) + CRC16_SIZE

    payload_size_L = (payload_size.to_bytes(2, "big"))[1]
    payload_size_H = (payload_size.to_bytes(2, "big"))[0]

    formed_message.append(payload_size_H)
    formed_message.append(payload_size_L)
    formed_message += bytearray(msg_payload)
    crc = _CRC_FUNC(bytearray(msg_payload))

    formed_message.append(((crc >> 8) & 0xff))
    formed_message.append(crc & 0xff)
    formed_message += bytearray(msg_end)
    return formed_message


def parse_response_data(r_data, failure_error):
    if(len(r_data) < 1):
        return ERROR.GENERIC
    msg_length = r_data[3] << 8 | r_data[4]
    payload_bytes = (r_data[5:][:msg_length - CRC16_SIZE])
    payload_computed_CRC = _CRC_FUNC(bytearray(payload_bytes))
    payload_received_CRC = r_data[len(
        r_data) - 4] << 8 | r_data[len(r_data) - 3]
    if(payload_computed_CRC == payload_received_CRC):
        return payload_bytes
    else:
        return failure_error


def send_command(command, payload=bytearray([]), encode=False, verbose_message="My job here is done."):
    msg_payload = []
    msg_payload.append(command.value)

    if(encode):
        msg_payload += list(bytearray(payload.encode()))
    else:
        msg_payload += list(bytearray(payload))

    serial_port.write(compose_message(MESSAGE_TYPE.COMMAND.value, msg_payload))
    time.sleep(1)
    response_data = []

    while(serial_port.in_waiting > 0):
        response_data.append(int.from_bytes(serial_port.read(), "little"))
    parsed_response = parse_response_data(response_data, ERROR.CRC_FAIL)

    if(parsed_response != ERROR.CRC_FAIL):
        print(f"{verbose_message}: OK")
        print()
        return parsed_response
    else:
        print("data corrupted")
        print("Please relaunch the script to retry")
        return ERROR.CRC_FAIL


# Python to API FUNCTIONS

def generate_token(client_id, secret_id):
    url = 'https://api2.arduino.cc/iot/v1/clients/token'
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    data = {'grant_type': 'client_credentials',
            'client_id': client_id,
            'client_secret': secret_id,
            'audience': 'https://api2.arduino.cc/iot'
            }
    response = send_request(requests.Request(
        "POST", url, headers=headers, data=data), print_request=False, print_response=False)
    token = json.loads(response.text)['access_token']
    return token


def add_device(token, device_name, fqbn, type, serial):
    url = 'http://api2.arduino.cc/iot/v2/devices'
    headers = {'content-type': 'application/x-www-form-urlencoded',
               'Authorization': 'Bearer ' + token
               }
    data = {'fqbn': fqbn,
            'name': device_name,
            'type': type,
            'serial': serial
            }
    response = send_request(requests.Request(
        "PUT", url, headers=headers, data=data), print_request=False, print_response=False)
    print(response)
    device_id = json.loads(response.text)['id']
    return device_id


def delete_device(device_name, device_id, force_deletion=False):
    if not force_deletion:
        confirm_delete = input(
            f'Are you sure you want to delete {device_name}? [Y,n]: ')
        if confirm_delete == 'Y':
            pass
        else:
            print(f'{device_name} will not be deleted')
            return

    url = f'http://api2.arduino.cc/iot/v2/devices/{device_id}'
    headers = {'content-type': 'application/x-www-form-urlencoded',
               'Authorization': 'Bearer ' + token
               }

    response = send_request(requests.Request(
        "DELETE", url, headers=headers), print_request=False, print_response=False)
    if response.status_code == 200:
        print(f'device {device_name} with ID {device_id} has been deleted')
    else:
        print(f'device {device_name} with ID {device_id} could not be deleted')


def send_csr(token, csr, device_id):
    url = 'http://api2.arduino.cc/iot/v2/devices/' + device_id + '/certs'
    headers = {'content-type': 'application/json',
               'Authorization': 'Bearer ' + token
               }
    data_cert = {'ca': 'Arduino',
                 'csr': csr,
                 'enabled': True
                 }
    data = json.dumps(data_cert)
    # response = requests.put(url, headers=headers, data=json.dumps(data_cert))
    response = send_request(requests.Request(
        "PUT", url=url, headers=headers, data=data), print_request=True, print_response=True)
    return json.loads(response.text)['compressed']


def boards_list():
    device_list = []
    ino_board_list = subprocess.run(
        ["arduino-cli", "board", "list", "--format", "json"], capture_output=True)

    serial_devices_json = json.loads(ino_board_list.stdout)
    for device in serial_devices_json:
        if "boards" not in device:
            continue
        my_board = SimpleNamespace(**device["boards"][0])
        my_board.address = device['address']
        if "serial_number" in device:
            my_board.serial_number = device['serial_number']
        my_board.type = my_board.fqbn.rpartition(':')[2]
        device_list.append(my_board)
    return device_list


def get_sketch_info():
    print('Querying Crypto Provisioning Sketch...')
    msg_payload = []
    msg_payload.append(COMMAND.GET_SKETCH_INFO.value)
    serial_port.write(compose_message(MESSAGE_TYPE.COMMAND.value, msg_payload))
    time.sleep(.5)
    response_data = []
    while(serial_port.in_waiting > 0):
        response_data.append(int.from_bytes(serial_port.read(), "little"))
    if(len(response_data) < MIN_MESSAGE_LENGTH):
        return ERROR.SKETCH_UNKNOWN
    parsed_response = parse_response_data(response_data, ERROR.SKETCH_UNKNOWN)
    return parsed_response


def connect_to_board(board):
    waiting_for_serial = True
    time.sleep(1)
    while waiting_for_serial:
        try:
            print(
                f"Attempting connection to {board.name} on port {board.address}")
            # serial_port_handler = serial.Serial(board.address, 1200, write_timeout=2)
            # serial_port_handler.open()
            # serial_port_handler.close()
            sleep(1)
            serial_port_handler = serial.Serial(
                board.address, 57600, write_timeout=5)
            waiting_for_serial = False
        except SerialException as se:
            print(f"cannot connect to serial:\n{se}")
            waiting_for_serial = True
        time.sleep(2)
    return serial_port_handler


def serial_disconnect():
    serial_port.close()


def find_binary(fw_file_path):
    try:
        fw_file_res = open(fw_file_path, 'r')
        fw_file_res.close()
        return True

    except FileNotFoundError as e:
        print(e)
        return False


def upload_sketch(board):
    platform_id = board.fqbn.rpartition(':')[0]
    binary_file_path = f'cryptoconfig_fw/{board.fqbn.replace(":", ".")}.bin'
    print(binary_file_path)
    if find_binary(binary_file_path):
        print("Uploading pre-compiled ArduinoIoTCloud-CryptoConfig Sketch")
        uploading_sketch = subprocess.Popen(["arduino-cli", "upload", "--input-file",
                                            binary_file_path, "-b",
                                            board.fqbn, "-p", board.address],
                                            stdout=subprocess.PIPE)
        while True:
            output = uploading_sketch.stdout.readline().decode()
            if output == '' and uploading_sketch.poll() is not None:
                break
            if output:
                print(output.strip())
        uploading_sketch.wait()
    else:
        print(f"Installing {platform_id} core")
        installing_core = subprocess.Popen(
            ["arduino-cli", "core", "install", platform_id], stdout=subprocess.PIPE)
        while True:
            output = installing_core.stdout.readline().decode()
            if output == '' and installing_core.poll() is not None:
                break
            if output:
                print(output.strip())
        installing_core.wait()

        print()

        print("Installing ArduinoIoTCloud library")
        installing_lib = subprocess.Popen(
            ["arduino-cli", "lib", "install", "ArduinoIoTCloud"], stdout=subprocess.PIPE)
        while True:
            output = installing_lib.stdout.readline().decode()
            if output == '' and installing_lib.poll() is not None:
                break
            if output:
                print(output.strip())
        installing_lib.wait()

        print()

        print("Installing ArduinoECCX08 library")
        installing_lib = subprocess.Popen(
            ["arduino-cli", "lib", "install", "ArduinoECCX08"], stdout=subprocess.PIPE)
        while True:
            output = installing_lib.stdout.readline().decode()
            if output == '' and installing_lib.poll() is not None:
                break
            if output:
                print(output.strip())
        installing_lib.wait()

        print()

        print("Installing Arduino STL library")
        installing_lib = subprocess.Popen(
            ["arduino-cli", "lib", "install", "ArduinoSTL"], stdout=subprocess.PIPE)
        while True:
            output = installing_lib.stdout.readline().decode()
            if output == '' and installing_lib.poll() is not None:
                break
            if output:
                print(output.strip())
        installing_lib.wait()

        print()

        print("Installing uCRC16Lib library")
        installing_lib = subprocess.Popen(
            ["arduino-cli", "lib", "install", "uCRC16Lib"], stdout=subprocess.PIPE)
        while True:
            output = installing_lib.stdout.readline().decode()
            if output == '' and installing_lib.poll() is not None:
                break
            if output:
                print(output.strip())
        installing_lib.wait()

        print()

        print("Compiling and Uploading ArduinoIoTCloud-CryptoConfig Sketch")
        compiling_sketch = subprocess.Popen(["arduino-cli", "compile",
                                            "ArduinoIoTCloud-CryptoConfig", "-b",
                                             board.fqbn, "-u", "-p", board.address],
                                            stdout=subprocess.PIPE)
        while True:
            output = compiling_sketch.stdout.readline().decode()
            if output == '' and compiling_sketch.poll() is not None:
                break
            if output:
                print(output.strip())
        compiling_sketch.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Arduino IoT Cloud Crypto-Element Provisioning Assistant')
    parser.add_argument('--api_credentials_file',
                        help='Provide the path to the file containing Client ID and API Secret. Example: --api_credentials_file=/home/myuser/ArduinoIoTCloudAPI_credentials.json')
    parser.add_argument(
        '--device_name', help='Choose the name your device will have in your dashboard. Example: --device_name=myNanoIoT')
    parser.add_argument(
        '--device_port', help='Select the device you want provision via the the serial port. Example: --device_port=COM1')
    args = parser.parse_args()

if(args.api_credentials_file):
    json_config_file = args.api_credentials_file
else:
    home = os.path.expanduser('~')
    json_config_file = home + "/ArduinoIoTCloudAPI_credentials.json"

try:
    with open(json_config_file) as json_cfg:
        api_credentials = json.load(json_cfg)
        client_id = api_credentials['client_id']
        secret_id = api_credentials['secret_id']
    json_cfg.close()
except Exception as e:
    print("*****  ERROR  *****")
    print(e)
    print(
        f"Failed to load Arduino IoT API Credentials JSON [{json_config_file}]\n")
    print("This file is supposed to be found in the user's home directory.")
    print("Alternatively it can be supplied as a parameter in the command.\n")
    print("e.g.: python provisioning-helper.py --api_credentials_file PATH_TO_FILE.json\n")
    print("You can rename the supplied ArduinoIoTCloudAPI_credentials-example.json")
    print("to ArduinoIoTCloudAPI_credentials.json and use your generated API credentials")
    exit()

if(args.device_name):
    device_name = args.device_name
else:
    device_name = f"IOTDevice_{int(time.time())}"  # input('Device name: ')
print(f"Provisioning device with name {device_name}")

device_list = boards_list()
if len(device_list) < 1:
    exit('No board attached/discovered')

if args.device_port:
    selected_board = [ d for d in device_list if d.address == args.device_port ][0]
else:
    selected_board = device_list[0]

token = generate_token(client_id, secret_id)
device_id = add_device(token, device_name, selected_board.fqbn,
                       selected_board.type, selected_board.serial_number)
print(f"IoT Cloud generated Device ID: {device_id}")

# confirm = input("touch? ")
# if confirm == 'Y':
#     serial_port_handler = serial.Serial(selected_board.address, 1200, write_timeout=2)
#     # serial_port_handler.open()
#     sleep(1)
#     serial_port_handler.close()
#     sleep(1)

# confirm = input("touch? ")
# if confirm == 'Y':
#     serial_port_handler = serial.Serial(selected_board.address, 1200, write_timeout=2)
#     # serial_port_handler.open()
#     sleep(1)
#     serial_port_handler.close()
#     sleep(1)

# input('any key to continue...')

serial_port = connect_to_board(selected_board)
time.sleep(1)

sketch_unknown = True
while(sketch_unknown):
    if(get_sketch_info() != (ERROR.SKETCH_UNKNOWN)):
        print(f"Provisioning Sketch found on {selected_board.name}")
        sketch_unknown = False
        break
    print("Provisioning Sketch not on board. Installation in progress...")
    upload_sketch(selected_board)
    time.sleep(1)
    print("Provisioning Sketch uploaded")
    time.sleep(1)
    serial_port = connect_to_board(selected_board)
    time.sleep(2)


# send GET_CSR command (has payload > 0)
# pass in the device_name as payload
# ******* CHANGE TO THE DEVICE ID RETURNED BY THE API *********
print(f"REQUESTING CSR for Device with ID: {device_id}")

print(device_id)
print(device_id.encode())
print(bytearray(device_id.encode()))
print(list(bytearray(device_id.encode())))

csr = send_command(command=COMMAND.GET_CSR, payload=list(
    bytearray(device_id.encode())), encode=False, verbose_message="CSR Obtained")
print(csr)

if(csr != ERROR.CRC_FAIL):
    print("CSR received")
    csr = bytearray(csr).decode('utf-8')
else:
    print("CSR REQUEST FAILED. Data returned below:")
    print(csr)
    exit()

certificate = send_csr(token, csr, device_id)
print(certificate)

print("Requesting Begin Storage")
send_command(command=COMMAND.BEGIN_STORAGE,
             verbose_message="Crytpo Storage INIT OK")

year = certificate['not_before'][:4]
print(f"Sending Year: {year}")
send_command(COMMAND.SET_YEAR, year, True, "YEAR set")

month = certificate['not_before'][5:7]
print(f"Sending Month: {month}")
send_command(COMMAND.SET_MONTH, month, True, "MONTH set")

day = certificate['not_before'][8:10]
print(f"Sending Day: {day}")
send_command(COMMAND.SET_DAY, day, True, "DAY set")

hour = certificate['not_before'][11:13]
print(f"Sending Hour: {hour}")
send_command(COMMAND.SET_HOUR, hour, True, "HOUR set")

years_validity = "31"
print(f"Sending Validity (years): {years_validity}")
send_command(COMMAND.SET_VALIDITY, years_validity, True, "VALIDITY set")

cert_serial = bytearray.fromhex(certificate['serial'])
print(f"Sending Certificate Serial: {cert_serial}")
send_command(COMMAND.SET_CERT_SERIAL, cert_serial, False, "Serial set")

cert_authority_key_id = bytearray.fromhex(
    certificate['authority_key_identifier'])
print(f"Sending Certificate Authority Key: {cert_authority_key_id}")
send_command(COMMAND.SET_AUTH_KEY, cert_authority_key_id,
             False, "Authority Key ID set")

signature = bytearray.fromhex(
    certificate['signature_asn1_x'] + certificate['signature_asn1_y'])
print(f"Sending Signature: {signature}")
send_command(COMMAND.SET_SIGNATURE, signature, False, "Signature set")
time.sleep(1)
print("Requesting End Storage")
send_command(command=COMMAND.END_STORAGE, verbose_message="End Storage")

time.sleep(2)
print("Requesting Certificate Reconstruction")
send_command(command=COMMAND.RECONSTRUCT_CERT,
             verbose_message="Reconstrucing Certificate")

print('Device provisioning successful')
print(f'IoT Cloud Device Name: {device_name}')
print(f'IoT Cloud Device ID: {device_id}')

print('My job here is done!')
