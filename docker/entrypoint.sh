#!/bin/sh
# Entrypoint: make the mounted data volume writable by the unprivileged user, then
# drop to it before running monohunter.
#
# Why: the container hardens by running as a non-root user (uid 10001). A named Docker
# volume is auto-chowned to that user, but some hosts (Fly.io, plain bind mounts) attach
# the volume as root:root — the unprivileged process then can't write /data. So we start
# as root ONLY to chown the mountpoint, then hand off to the unprivileged user via gosu.
# Under `docker run` with an already-owned named volume this chown is a harmless no-op.
#
# Every arg is passed straight to the `monohunter` CLI, so the image behaves exactly like
# before: `docker run <image> run --tic ...`, `... watch-loop --hint 90 ...`, etc.
set -e

if [ "$(id -u)" = "0" ]; then
    # non-recursive: the mountpoint itself; subdirs are created by the app as its own user
    chown monohunter:monohunter /data 2>/dev/null || true
    exec gosu monohunter monohunter "$@"
fi

exec monohunter "$@"
