#!/usr/bin/env python3
"""Prepares the checkout of a syncstorage-rs release for the build of syncstorage-rs.yml.

Usage: syncstorage-rs-build.py <source-checkout-dir>

After the upstream patches, before docker build; the same for every backend and architecture.
This file is in the key of the images the workflow reuses: a change of it builds them again.

- version.json: what upstream's CI fills in (served at /__version__, "TBD" otherwise), from
  SERVICE_TAG, SERVICE_REPOSITORY_NAME and BUILD_URL, and the checkout's commit.
- The Dockerfile's cache mounts (RUN --mount=type=cache: cargo's registry and git, /app/target)
  are dropped. Upstream's Dockerfile cooks the dependencies first (cargo-chef, keyed on its
  recipe of the Cargo.lock and manifests), but into those mounts: they are empty on every new
  GitHub runner and no registry cache exports them, so the cooked layer came back from the
  build cache without the compiled dependencies and `cargo install` compiled them all again.
  Without the mounts they are in the layer itself, which the registry cache keeps (mode=max):
  only syncstorage-rs' own crates compile while the recipe is the same.
- The release build strips DWARF debug info. pip reads the builder's wheels through a
  read-only BuildKit mount so the wheel archives never enter a runtime image layer.
"""

import json
import os
import re
import subprocess
import sys

# an option of RUN, whatever the order of its fields, and the line continuation after it
CACHE_MOUNT = re.compile(r"--mount=(?=[^\s]*\btype=cache\b)[^\s]+[ \t]*(?:\\\n[ \t]*)?")


def drop_cache_mounts(text):
    """The Dockerfile without its cache mounts, and how many there were."""
    return CACHE_MOUNT.subn("", text)


def mount_wheels(text):
    """Replace the wheel COPY and its one consuming RUN together."""
    instructions = re.split(r"(?<!\\)\n", text)
    wheel_copy = "COPY --from=builder /app/wheels /tmp/wheels"
    consumers = [line for line in instructions if "/tmp/wheels" in line and line != wheel_copy]
    if instructions.count(wheel_copy) != 1 or len(consumers) != 1:
        return text
    install = consumers[0]
    cleanup = "rm -rf /tmp/wheels /root/.cache/pip"
    if not (install.startswith("RUN pip3 install ") and "--find-links=/tmp/wheels" in install
            and install.endswith(cleanup)):
        return text
    mount = "RUN --mount=type=bind,from=builder,source=/app/wheels,target=/tmp/wheels"
    pip = install.removeprefix("RUN ").removesuffix(cleanup)
    instructions[instructions.index(install)] = f"{mount} {pip}rm -rf /root/.cache/pip"
    instructions.remove(wheel_copy)
    return "\n".join(instructions)


def main(argv):
    if len(argv) != 1:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    checkout = argv[0]
    commit = subprocess.run(["git", "-C", checkout, "rev-parse", "HEAD"], check=True,
                            capture_output=True, text=True).stdout.strip()
    version = {"version": os.environ["SERVICE_TAG"], "commit": commit,
               "source": f"https://github.com/{os.environ['SERVICE_REPOSITORY_NAME']}",
               "build": os.environ["BUILD_URL"]}
    with open(os.path.join(checkout, "version.json"), "w") as f:
        f.write(json.dumps(version, separators=(",", ":")) + "\n")
    print(f"version.json: {json.dumps(version, separators=(',', ':'))}")

    path = os.path.join(checkout, "Dockerfile")
    with open(path) as f:
        text, count = drop_cache_mounts(f.read())
    if count == 0:
        print("::warning title=syncstorage-rs-build.py::the Dockerfile has no cache mount (RUN --mount=type=cache) "
              "any more: nothing dropped, check how it caches the compiled dependencies now")
    elif "type=cache" in text:
        print(f"::error title=syncstorage-rs-build.py::a cache mount of the Dockerfile is left after dropping {count}")
        return 1
    release_strip = "ENV CARGO_PROFILE_RELEASE_STRIP=debuginfo"
    builder = re.search(r"^FROM [^\n]+ AS builder$", text, re.MULTILINE | re.IGNORECASE)
    if not builder:
        print("::warning::Cargo builder stage changed; check the release binary's debug info")
    elif not text[builder.end():].startswith("\n" + release_strip + "\n"):
        text = text[:builder.end()] + "\n" + release_strip + text[builder.end():]
    mounted = mount_wheels(text)
    if mounted == text:
        print("::warning::Wheel install layout changed; keeping upstream's wheel handling")
    with open(path, "w") as f:
        f.write(mounted)
    print(f"Dockerfile: {count} cache mounts dropped")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
