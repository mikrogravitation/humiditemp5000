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
import argparse


def make_argument_parser():

    parser = argparse.ArgumentParser(description="deploy files from current directory, based on the deploy-listing file")
    parser.add_argument("device", type=str,
                        help="device name; this should probably be the device hostname. it has to match a device entry in devices.yaml, and it has to resolve to the IP of the device.")
    parser.add_argument('--noop', action="store_true",
                        help="do a no-op run (not actually pushing changes to the device)")
    parser.add_argument('--no-reboot', action="store_true",
                        help="skip the reboot step after finishing updates")

    return parser


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


def delete_remote_file(remote, glitter, filename, noop=False):

    noop_prefix = b"--noop " if noop else b""
    sparkle = make_sparkle(glitter, noop_prefix + filename.encode("ascii"))

    print(f"  deleting file '{filename}'...")

    response = requests.delete(
        f"http://{remote}:5000/ota/{filename}", params=dict(sparkle=sparkle, noop="yes" if noop else "no")
    )

    print(
        f"   => {response.status_code} {response.reason}: {response.text}"
    )
    print()

    if response.status_code != 200:
        raise RuntimeError("non-200 response code")


def push_remote_file(remote, glitter, filename, file_contents=None, noop=False):

    if not file_contents:
        with open(filename, "rb") as f:
            file_contents = f.read()

    noop_prefix = b"--noop " if noop else b""
    sparkle = make_sparkle(glitter, noop_prefix + filename.encode("ascii") + b" " + file_contents)

    print(f"  pushing file '{filename}'...")

    response = requests.put(
        f"http://{remote}:5000/ota/{filename}",
        params=dict(sparkle=sparkle, noop="yes" if noop else "no"),
        data=file_contents,
    )

    print(
        f"   => {response.status_code} {response.reason}: {response.text}"
    )
    print()

    if response.status_code != 200:
        raise RuntimeError("non-200 response code")


def get_remote_file(remote, filename):

    print(f"  getting file '{filename}'...")

    response = requests.get(f"http://{remote}:5000/ota/{filename}")

    if response.status_code != 200:
        print(
            f"   => {response.status_code} {response.reason}: {response.text}"
        )
        print()
        raise RuntimeError("non-200 response code")

    else:
        print(f"   => {response.status_code} {response.reason}") 
        print()

    return response.text


def reboot_remote(remote):

    response = requests.get(f"http://{remote}:5000/reboot")

    print(
        f" => {response.status_code} {response.reason}: {response.text}"
    )


if __name__ == "__main__":

    parser = make_argument_parser()
    args = parser.parse_args()

    device = args.device

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

    made_changes = False

    for filename in all_file_names:

        old_sha1 = remote_files.get(filename, "--")
        new_sha1 = local_files.get(filename, "--")

        if new_sha1 == old_sha1:
            continue

        made_changes = True

        print(f"File {filename}:")

        print(f"  old: {old_sha1}")
        print(f"  new: {new_sha1}")
        print()

        if new_sha1 != "--":

            if filename == "config.py":
                new_file_contents = config_py

            else:
                with open(filename, "rb") as f:
                    new_file_contents = f.read()

        if old_sha1 != "--" and new_sha1 != "--":

            try:
                # config.py is generated and never in git, so we have to retrieve it
                if filename == "config.py":
                    old_file_contents = get_remote_file(device, "config.py")
                else:
                    old_file_contents = repo.git.cat_file("blob", old_sha1)
            except:
                old_file_contents = None

            if old_file_contents:
                longest_line = 0
                print("    ┌─────────")
                for line in difflib.unified_diff(
                        old_file_contents.splitlines(),
                        new_file_contents.decode("utf-8").splitlines(),
                        fromfile="old", tofile="new",
                        lineterm=""):

                    longest_line = max(longest_line, len(line))
                    print("    │ " + line)
                print("    └" + "─" * (longest_line + 2))

            else:
                print("  (no diff available)")

            print()

        if new_sha1 == "--":
            # this file has been removed, delete it
            delete_remote_file(device, glitter, filename, noop=args.noop)

        else:
            push_remote_file(device, glitter, filename, file_contents=new_file_contents, noop=args.noop)
            pass

    if not made_changes:
        print("nothing to do!")

    elif args.noop:
        print("no-op run, skipping reboot")

    elif args.no_reboot:
        print("all files synced, skipping reboot")

    else:
        print("rebooting...")
        reboot_remote(device)
