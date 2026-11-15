# Single-VM deployment and GitHub Actions

Target: Ubuntu 24.04 x86_64, Node 22 through NVM, Python 3.12, SUMO 1.27.1.
One VM runs Next.js, exactly one Uvicorn worker/SUMO owner, and Caddy for HTTPS
and WebSockets. Existing authentication and control rules are unchanged.

## What the workflow does

`.github/workflows/vm.yml` checks main pushes and pull requests targeting main.
Backend checks cover the planner, emergency controller, configuration, API
authorization, and analytics insights. Frontend checks run lint, types, voice tests,
and production build.
These are focused checks, not a full London simulation benchmark or vision test.

Only a successful main push (or manual run on main) deploys. GitHub-hosted runners
upload the exact checked Git commit over SSH. No runner executes on the VM and no
GitHub token or repository credential is stored there. Configure the `production`
environment to allow only main. Concurrent deploys are serialized.

Each deploy creates a separate `~/flowgency/releases/<sha>.<suffix>` with its own
Python environment and Next.js build. Secrets stay outside releases in `shared`.
A failed install/build does not stop the live version. Activation switches the
`current` symlink, restarts the two services, and checks HTTP health. A failed
activation attempts to restore the prior release; it does not restore an active
SUMO run, undo database changes, or prove Auth0/ElevenLabs work externally.

**Every successful deploy interrupts the current simulation.** Deploy between
demos. The pipeline is not zero downtime. The shared SQLite database survives
release switches. No schema rollback is implemented: review future migrations.

## One-time server setup

Complete the prerequisite installs already used for this VM:

```bash
sudo apt-get update
sudo apt-get install -y git curl ca-certificates build-essential python3-venv libxrender1 libgl1
# Node 22 must be available through ~/.nvm/nvm.sh.
```

Use the existing SSH user, `razvanandronie2005`, for the MVP. From a checkout of
the deployment branch (or main after it is merged), run:

```bash
mkdir -p "$HOME/flowgency/shared" "$HOME/flowgency/releases" "$HOME/flowgency/incoming"
chmod 700 "$HOME/flowgency/shared"
cp -n deploy/frontend.env.example "$HOME/flowgency/shared/frontend.env"
cp -n deploy/backend.env.example "$HOME/flowgency/shared/backend.env"
chmod 600 "$HOME/flowgency/shared/"*.env
nano "$HOME/flowgency/shared/frontend.env"
nano "$HOME/flowgency/shared/backend.env"
mkdir -p "$HOME/.config/systemd/user"
cp deploy/flowgency-*.service "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable flowgency-backend flowgency-frontend
sudo loginctl enable-linger "$USER"
```

Keep placeholder values out of the real files. Generate a new Auth0 cookie secret
with `openssl rand -hex 32`; retain it across releases. Do not share its output.
Do not start the services until a first release has been prepared by the workflow.
After editing service units in a future release, reinstall the units and run
`systemctl --user daemon-reload` before deploying; units are not auto-updated.

## DNS, HTTPS, and Auth0

Choose a domain/subdomain (a free DNS subdomain is also suitable) and point its A
record at the VM's public IPv4. The initially allocated address is ephemeral;
reserve it as static before relying on it across VM stop/start cycles. Public IP
and network traffic have their own cloud costs.

Install Caddy following its official Ubuntu instructions:
https://caddyserver.com/docs/install#debian-ubuntu-raspbian
Copy `deploy/Caddyfile.example` to `/etc/caddy/Caddyfile`, replace the example
hostname, validate with `sudo caddy validate --config /etc/caddy/Caddyfile`, then
`sudo systemctl reload caddy`. Permit inbound TCP 80/443 in Google Cloud. App
ports 3000/8000 bind only to loopback. Caddy preserves the WebSocket path and
routes command requests through the existing authenticated Next.js proxy.
The protected `/api/analytics/insights` request also stays on that proxy so the
frontend can attach its Auth0 token. To use the Gemini review added to main, set
`GEMINI_API_KEY` (and optionally `GEMINI_MODEL`) in `shared/backend.env`; without
that optional key, the review returns the documented 503 while other features
continue working.

Set `APP_BASE_URL` and `NEXT_PUBLIC_BACKEND_URL` to that same HTTPS origin in
`shared/frontend.env`; keep `BACKEND_URL=http://127.0.0.1:8000`. This must happen
before building: the browser backend URL is embedded in the frontend bundle.

In the existing Auth0 Regular Web Application, add:

- Allowed Callback URLs: `https://YOUR_HOST/auth/callback`
- Allowed Logout URLs: `https://YOUR_HOST`
- Allowed Web Origins: `https://YOUR_HOST`

Keep existing local entries if still used. Preserve the tenant, API audience,
roles, permissions, and MFA settings. Do not change the API identifier to the
public hostname unless the team's Auth0 configuration explicitly changes too.

## GitHub-to-VM SSH access

Generate a dedicated key on a trusted computer, not in the repository:

```bash
ssh-keygen -t ed25519 -f "$HOME/.ssh/flowgency_actions" -C flowgency-actions
```

For this unattended key use an empty passphrase. Append only its `.pub` content
to the VM user's `~/.ssh/authorized_keys` (directory mode 700, file mode 600).
Use the `restrict` authorized_keys option to disable forwarding and PTY:
`restrict ssh-ed25519 AAAA... flowgency-actions`.
The key can execute commands as the app user; give it no sudo permissions. A
compromised deployment key can access that user's app secrets. Treat it as a secret.

Google-managed SSH keys/OS Login can change how keys are accepted. Confirm the
instance's SSH mechanism before editing authorized_keys; if OS Login is enabled,
configure an appropriate deploy identity rather than disabling OS Login blindly.
Allow direct TCP 22 connectivity for the GitHub-hosted runner, or adapt the
workflow to Google IAP/OIDC; this SSH template does not configure GCP firewall.

Read the server's public host key in the trusted browser SSH session:

```bash
cat /etc/ssh/ssh_host_ed25519_key.pub
```

Construct a known_hosts line `VM_PUBLIC_IP ssh-ed25519 AAAA...` from that verified
key. Do not use an unverified network `ssh-keyscan` in the deployment workflow.

GitHub repository Settings -> Environments -> production: allow main only, then
add these **environment secrets**:

| Secret | Value |
| --- | --- |
| DEPLOY_HOST | VM public IP or stable SSH hostname |
| DEPLOY_USER | `razvanandronie2005` |
| DEPLOY_SSH_KEY | Full private deployment key, including header/footer |
| DEPLOY_KNOWN_HOSTS | Verified known_hosts line described above |

App credentials stay on the VM, not in workflow YAML, repository files, or chat.
No automatic deployment can run until the workflow is merged into main, server
setup is complete, and secrets/network access are configured.

## Verification and maintenance

First trigger Actions -> Check and deploy VM -> Run workflow on main. Then verify:

```bash
systemctl --user status flowgency-backend flowgency-frontend
curl --fail http://127.0.0.1:8000/api/health
curl --fail http://127.0.0.1:3000/ -o /dev/null
journalctl --user -u flowgency-backend -u flowgency-frontend -n 80 --no-pager
```

On a fresh server, populate the committed analytics reference data once (and
repeat deliberately when that reference data changes). The loader preserves
recorded simulation runs. Keep the database target identical to the backend:

```bash
cd "$HOME/flowgency/current"
set -a
source "$HOME/flowgency/shared/backend.env"
set +a
export FLOWGENCY_ANALYTICS_DB="${FLOWGENCY_ANALYTICS_DB:-$HOME/flowgency/shared/analytics.sqlite3}"
.venv/bin/python -m backend.analytics.load >/dev/null
```

From two browsers, verify public HTTPS, Auth0 operator login/MFA, a London run,
the spectator receiving the same run, and ElevenLabs playback. Local HTTP health
alone does not establish these. Logs may contain operational data: redact before
sharing. Check disk space before each demo (`df -h /`): release directories include
SUMO and node_modules. Keep the current release and a previous known-good version;
older releases are deliberately not auto-deleted by this MVP script. Remove only
verified obsolete release paths during maintenance. GitHub run logs identify the
deployed SHA; `readlink -f ~/flowgency/current` identifies the active release.

Rollback to an existing known-good directory is a symlink switch followed by
`systemctl --user restart flowgency-backend flowgency-frontend`. It also resets the
simulation. Workflow concurrency does not replace branch protection: require CI
checks/review on main so unreviewed branches cannot deploy.
