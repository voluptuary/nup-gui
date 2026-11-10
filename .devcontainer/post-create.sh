#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# System dependencies belong in the image. Never run apt or initialize Wine
# here: workspace creation should only install the small local Python package.
echo "Installing NUP for the current Python interpreter..."
timeout --foreground 180s python -m pip install \
  --disable-pip-version-check --no-input --timeout 30 --retries 2 \
  --user -e ./tools/nup
echo "NUP environment ready. Run tools/nup/build_wine.sh when a Windows build is needed."
