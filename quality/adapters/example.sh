#!/usr/bin/env sh
set -eu

# Replace this example with a project-native adapter.
# 0 pass, 1 quality failure, 2 configuration error, 3 infrastructure error.

if [ ! -f "quality/policy.toml" ]; then
  echo "quality/policy.toml is missing" >&2
  exit 2
fi

echo "Example adapter is not configured" >&2
exit 2
