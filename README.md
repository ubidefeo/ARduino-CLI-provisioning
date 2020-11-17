# cli-getting-started
Arduino IoT Cloud "Getting Started" via command line

Based off initial work by Luigi Gubello (@luigigubello).
Greatly influenced by Martino Facchin (@facchinm).

**NOTE:** Because of how Windows tends to rename Serial ports when you don't look at it, it is advised to manually upload the `ProvisioningADVANCED` sketch rather than letting the Python script do that automatically.
Works great on Mac OS and Linux
### Usage

1. Go to [https://create.arduino.cc/iot/things](https://create.arduino.cc/iot/things) and generate the API Client ID and Secret ID.
2. Install **arduino-cli**, following [the instruction](https://arduino.github.io/arduino-cli/installation/).
3. Install the requirements (`requirements.txt`)
4. Connect your Arduino board and run `python provisioning-helper.py`
5. You will be asked to connect your Arduino board. This only works if your board has ECCX08 Cryptography Element
6. The script will query your board for a Sketch ID and in case none is returned it will use Arduino CLI to automatically upload the firmware required (`ProvisioningADVANCED`)

Available arguments to the script are viewed by running `python provisioning-helper.py -h`.
You can specify a device name or have one generated for you based on timestamp.
The script expects a configuration file in the user home named `arduinoIoTCloudAPI.json` containing your Client ID and Secret ID as follows. A configuration file can be manually entered as an argument using the flag `-api_credentials_file`

```json
{
    "client_id": "XxXxXxXxXxXxXxXxXxXxXxXxXxXxXxXx",
    "secret_id": "XxXxXxXxXxXxXxXxXxXxXxXxXxXxXxXxXxXxXxXxXxXxXxXxXxXxXxXxXxXxXxXx"
}
```
This is a fresh repo and will eventually be transferred to Arduino, please file issues for questions.

Ubi
