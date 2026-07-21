#!/usr/bin/env bash
# Called by systemd --user to mount BlossomFS
exec python3 -m blooms_in_gnome "$@"
