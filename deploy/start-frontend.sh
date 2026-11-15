#!/usr/bin/env bash
set -euo pipefail
release="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$HOME/.nvm/nvm.sh"
nvm use 22 >/dev/null
cd "$release/frontend"
export NODE_ENV=production
exec node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3000
