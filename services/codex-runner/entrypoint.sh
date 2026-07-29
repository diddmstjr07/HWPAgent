#!/bin/sh
set -eu

data_dir="${AI_RUNNER_DATA_DIR:-/data}"
mkdir -p "$data_dir"
chown -R node:node "$data_dir"
chmod 700 "$data_dir"

exec gosu node "$@"
