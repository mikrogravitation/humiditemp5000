import sys
import json
import binascii
import hmac
import hashlib
import difflib
import requests
import git
import re
import yaml
from sparkle import Sparkle
from git import Repo


def make_sparkle(glitter, data):
    return binascii.hexlify(Sparkle(glitter, data).make_sparkle())


sensor_types = {
    "dht": {"port_type": "Pin"},
    "bme": {"port_type": "I2C"},
    "mhz": {"port_type": "UART"},
    "sds": {"port_type": "UART"},
    "counter": {"port_type": "Pin"},
}


def get_sensor_config_string(sensor_name, sensor_config):

    sensor_type_info = sensor_types[sensor_config["type"]]
    port_type = sensor_type_info["port_type"]

    port_match = re.match(port_type + r"\(([0-9]+)\)", sensor_config["port"])
    if not port_match:
        raise RuntimeError(
            f"Invalid port specification for sensor {sensor_name}: {sensor_config['port']} (sensor type {sensor_config['type']} needs port type {sensor_types[sensor_config['type']]['port_type']}"
        )

    port_index = int(port_match.group(1))

    return f"""{{"type": "{sensor_config["type"]}", "port": machine.{port_type}({port_index}), "description": "{sensor_config["description"]}"}}"""


def make_config_py(device_name, device_info):

    sensor_configs = "sensor_configs = {\n"
    for sensor_name, sensor_config in device_info["sensor_configs"].items():
        sensor_configs += (
            f'    "{sensor_name}": '
            + get_sensor_config_string(sensor_name, sensor_config)
            + ",\n"
        )
    sensor_configs += "}\n"

    file_contents = (
        f"""# this file is generated automatically from its corresponding entry in devices.yaml
import machine

hostname = "{device_name}"

"""
        + sensor_configs
    )

    return file_contents.encode("ascii")


def parse_file_listing(raw_listing):

    line_re = re.compile(r"([0-9a-zA-Z_.]+) ([0-9a-f]{40})")

    files = {}
    file_lines = raw_listing.split("\n")

    for line in file_lines:

        match_result = line_re.fullmatch(line)
        if not match_result:
            raise RuntimeError(f"line has invalid format in file listing: '{line}'")

        filename = match_result.group(1)
        checksum = match_result.group(2)

        files[filename] = checksum

    return files


def get_remote_file_listing(remote):

    print("trying to retrieve file listing...")

    response = requests.get(f"http://{device}:5000/ota-listing")
    assert response.status_code == 200

    print("  done.")
    print()

    return parse_file_listing(response.text)


def git_blob_hash(data):

    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\x00" + data).hexdigest()


def get_local_file_listing(config_py):

    local_files = {}
    repo = git.Repo()

    with open("deploy-listing") as f:

        for line in f:
            filename = line.strip()

            if filename == "config.py":
                # this file has been generated on-the-fly
                checksum = git_blob_hash(config_py)

            else:

                # compute the git checksum for this file, plus, add it into
                # git's object database
                checksum = repo.git.hash_object(filename, w=True)

            local_files[filename] = checksum

    return local_files


def delete_remote_file(remote, glitter, filename):

    sparkle = make_sparkle(glitter, filename.encode("ascii"))

    response = requests.delete(
        f"http://{remote}:5000/ota/{filename}", params=dict(sparkle=sparkle)
    )

    print(
        f"deleting file {filename}: {response.status_code} {response.reason}: {response.text}"
    )

    if response.status_code != 200:
        raise RuntimeError("non-200 response code")


def push_remote_file(remote, glitter, filename, file_contents=None):

    if not file_contents:
        with open(filename, "rb") as f:
            file_contents = f.read()

    sparkle = make_sparkle(glitter, filename.encode("ascii") + b" " + file_contents)

    response = requests.put(
        f"http://{remote}:5000/ota/{filename}",
        params=dict(sparkle=sparkle),
        data=file_contents,
    )

    print(
        f"pushing file {filename}: {response.status_code} {response.reason}: {response.text}"
    )

    if response.status_code != 200:
        raise RuntimeError("non-200 response code")


if __name__ == "__main__":

    device = sys.argv[1]

    with open("devices.yaml") as f:
        device_configs = yaml.safe_load(f)

    try:
        device_config = device_configs[device]

    except KeyError:
        raise RuntimeError(f"device {device} not found in devices.yaml")

    glitter = binascii.unhexlify(device_config["glitter"])

    config_py = make_config_py(device, device_config)

    # get file listings
    remote_files = get_remote_file_listing(device)
    local_files = get_local_file_listing(config_py)

    all_file_names = set(remote_files.keys()) | set(local_files.keys())

    #with open("config.py") as f:
    #    contents = f.read()
    #print("\n".join(difflib.unified_diff(contents.split("\n"), config_py.decode("ascii").split("\n"), fromfile="present", tofile="target")))

    repo = git.Repo()

    for filename in all_file_names:

        print(f"File {filename}:")

        old_sha1 = remote_files.get(filename, "--")
        new_sha1 = local_files.get(filename, "--")

        print(f"  old: {old_sha1}")
        print(f"  new: {new_sha1}")
        print()

        if new_sha1 == old_sha1:
            continue

        if new_sha1 != "--":

            if filename == "config.py":
                new_file_contents = config_py

            else:
                with open(filename) as f:
                    new_file_contents = f.read()

        if old_sha1 != "--" and new_sha1 != "--":

            try:
                old_file_contents = repo.git.cat_file("blob", sha1)
            except:
                old_file_contents = None

            if old_file_contents:
                for line in difflib.unified_diff(
                        old_file_contents.splitlines(keepends=True),
                        new_file_contents.splitlines(keepends=True),
                        fromfile="old", tofile="new"):

                    print("  " + line)

            else:
                print(" (no diff available)")

            print()

        if new_sha1 == "--":
            # this file has been removed, delete it
            print("would delete file")
            #delete_remote_file(device, glitter, filename)

        else:
            print("would push file")
            #push_remote_file(device, glitter, filename, file_contents=new_file_contents)

    print("all good.")
