import sys
import json
import binascii
import hmac
import hashlib
import requests
import re
from sparkle import Sparkle
from git import Repo

device = sys.argv[1]


def make_sparkle(glitter, data):
    return binascii.hexlify(Sparkle(glitter, data).make_sparkle())


def get_remote_file_listing(remote):

    print("trying to retrieve file listing...")

    response = requests.get(f"http://{device}:5000/ota-listing")
    assert response.status_code == 200

    print("  done.")
    print()

    return parse_file_listing(response.text)


def get_local_file_listing(repo):

    local_files = set()

    with open("deploy-listing") as f:

        for line in f:
            filename = line.strip()

            # TODO: nicer error handling for when the file isn't there
            # compute the git checksum for this file, plus, add it into
            # git's object database
            checksum = repo.git.hash_object(filename, w=True)

            local_files.add((filename, checksum))

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


def push_remote_file(remote, glitter, filename):

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


def parse_file_listing(raw_listing):

    line_re = re.compile(r"([0-9a-zA-Z_.]+) ([0-9a-f]{40})")

    files = set()
    file_lines = raw_listing.split("\n")

    for line in file_lines:

        match_result = line_re.fullmatch(line)
        if not match_result:
            raise RuntimeError(f"line has invalid format in file listing: '{line}'")

        filename = match_result.group(1)
        checksum = match_result.group(2)

        files.add((filename, checksum))

    return files


if __name__ == "__main__":

    with open("glitter.json") as f:
        all_glitters = json.load(f)

    try:
        glitter = all_glitters[device]

    except KeyError:
        print(f"device {device} not found in glitterfile")

    glitter = binascii.unhexlify(glitter)

    # get file listings
    remote_files = get_remote_file_listing(device)
    local_files = get_local_file_listing(Repo())

    remote_file_names = set(filename for filename, _ in remote_files)
    local_file_names = set(filename for filename, _ in local_files)
    delete_these_files = remote_file_names - local_file_names

    # note that since these sets include both filenames and hashes,
    # removing everything that's in remote_files will only remove
    # files where the hashes match, leaving both new and changed
    # files.
    update_these_files = set(filename for filename, _ in (local_files - remote_files))

    print(f"files to delete: {len(delete_these_files)}")
    print(f"files to push: {len(update_these_files)}")
    print()

    for filename in delete_these_files:
        print(f"file {filename} will be removed.")
        delete_remote_file(device, glitter, filename)
        print()

    for filename in update_these_files:

        if filename in remote_file_names:
            print(f"file {filename} is being updated.")
        else:
            print(f"file {filename} is new.")

        push_remote_file(device, glitter, filename)
        print()

    print("all good.")
