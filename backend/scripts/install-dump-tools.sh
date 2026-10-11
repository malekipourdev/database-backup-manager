#!/usr/bin/env bash
# Copies the dump tools used by the panel out of the official server images into
# backend/.tools/, so integration tests can run real backups on a development or CI host.
#
# Usage: backend/scripts/install-dump-tools.sh
# Then:  export MBP_MYSQLDUMP_PATH=$PWD/backend/.tools/mysqldump
#        export MBP_MARIADB_DUMP_PATH=$PWD/backend/.tools/mariadb-dump
set -euo pipefail

TOOLS_DIR="$(cd "$(dirname "$0")/.." && pwd)/.tools"
mkdir -p "$TOOLS_DIR"

copy_from_image() {
  local image="$1" source="$2" target="$3"
  local id
  id="$(docker create "$image")"
  trap 'docker rm -f "$id" >/dev/null 2>&1 || true' RETURN
  docker cp -L "$id:$source" "$TOOLS_DIR/$target"
  chmod 0755 "$TOOLS_DIR/$target"
}

copy_from_image mysql:8.4 /usr/bin/mysqldump mysqldump
copy_from_image mariadb:11.8 /usr/bin/mariadb-dump mariadb-dump

"$TOOLS_DIR/mysqldump" --version
"$TOOLS_DIR/mariadb-dump" --version
echo "export MBP_MYSQLDUMP_PATH=$TOOLS_DIR/mysqldump MBP_MARIADB_DUMP_PATH=$TOOLS_DIR/mariadb-dump"
