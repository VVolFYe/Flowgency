#!/usr/bin/env bash
# Invoked by the workflow while holding ~/flowgency/deploy.lock.
set -euo pipefail
root="$HOME/flowgency"
release="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
[[ "$release" == "$root/releases/"* ]] || { echo 'Not a release directory'; exit 1; }
test -s "$root/shared/backend.env"
test -s "$root/shared/frontend.env"
source "$HOME/.nvm/nvm.sh"
nvm use 22 >/dev/null
cd "$release"

# Prepare everything away from the live release. Failure here leaves it running.
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt \
  'eclipse-sumo==1.27.1' 'sumo-data==1.27.1'
.venv/bin/sumo --version
.venv/bin/python -m unittest tests.test_cycle_planner tests.test_emergency_controller tests.test_simulation_configuration -v
ln -s "$root/shared/frontend.env" frontend/.env.production
(
  cd frontend
  npm ci
  npm run build
)

previous="$(readlink -f "$root/current" || true)"
rollback() {
  trap - ERR
  echo 'Activation failed; attempting to restore the previous release.' >&2
  if [[ -n "$previous" && -d "$previous" ]]; then
    ln -sfn "$previous" "$root/current.next"
    mv -Tf "$root/current.next" "$root/current"
    systemctl --user restart flowgency-backend flowgency-frontend || true
  else
    systemctl --user stop flowgency-backend flowgency-frontend || true
  fi
  exit 1
}
trap rollback ERR
ln -sfn "$release" "$root/current.next"
mv -Tf "$root/current.next" "$root/current"
systemctl --user restart flowgency-backend flowgency-frontend

healthy=false
for attempt in {1..30}; do
  if systemctl --user is-active --quiet flowgency-backend flowgency-frontend \
    && curl --fail --silent --max-time 3 http://127.0.0.1:8000/api/health >/dev/null \
    && curl --fail --silent --max-time 3 http://127.0.0.1:3000/ >/dev/null; then
    healthy=true
    break
  fi
  sleep 2
done
[[ "$healthy" == true ]] || rollback
trap - ERR
echo "Deployed $release"
