#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if command -v uv >/dev/null 2>&1; then
  uv tool install --force "$ROOT"
else
  python3 -m pip install --user --upgrade "$ROOT"
fi
printf '\nInstalled qg. Run: qg init --install\n'
