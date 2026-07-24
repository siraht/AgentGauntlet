#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else "Agent Quality Gauntlet requires Python 3.11+")'

if [ -f "$ROOT/aqg.pyz" ]; then
  exec python3 "$ROOT/aqg.pyz" setup "$@"
fi

if [ -x "$ROOT/qg" ]; then
  exec "$ROOT/qg" setup "$@"
fi

printf '%s\n' "No aqg.pyz or source launcher was found beside install-aqg.sh." >&2
exit 3
