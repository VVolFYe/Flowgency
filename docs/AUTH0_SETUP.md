# Auth0 setup for Flowgency

Flowgency uses one Auth0 development tenant, one Regular Web Application, and one custom API for the team. Auth0 Universal Login owns credentials and MFA; Flowgency never receives passwords or email OTP values. Access tokens remain in the encrypted Next.js server session and are forwarded to FastAPI only by the command proxy.

## 1. Tenant, application, and API

1. Create a development tenant in the Auth0 Dashboard.
2. Create **Applications > Applications > Flowgency Development** as a **Regular Web Application**.
3. In its settings configure exactly:

   ```text
   Allowed Callback URLs:
   http://localhost:3000/auth/callback

   Allowed Logout URLs:
   http://localhost:3000

   Allowed Web Origins:
   http://localhost:3000
   ```

   The callback is mounted by `@auth0/nextjs-auth0` v4 through `frontend/proxy.ts`; there is no v3 `pages/api/auth/[auth0]` route.
4. Create **Applications > APIs > Flowgency API**. Choose a stable identifier such as `https://api.flowgency.local`; this exact value is the audience in both frontend and backend environments. Use RS256.
5. In the API settings enable **Enable RBAC** and **Add Permissions in the Access Token**.

## 2. Connections and login methods

Under **Authentication > Passwordless**, enable **Email** and configure an OTP email. Enable the connection for `Flowgency Development`. The default connection name is `email`; if it differs, set `AUTH0_ANALYST_CONNECTION` to the Dashboard value.

Under **Authentication > Database**, enable the database connection used by operators for `Flowgency Development`. Its default Auth0 name is `Username-Password-Authentication`; set `AUTH0_OPERATOR_CONNECTION` if the tenant uses another name.

The access-selection page sends each button to the real Auth0 `/authorize` flow with its connection name:

- **Continue as Analyst** uses Passwordless Email OTP and returns to `/analyst`.
- **Operator Secure Access** uses the database connection, requests a fresh interactive login with `prompt=login`, and returns to `/operator`.

Choosing a button does not grant a role. The protected layout inspects permissions in the API access token after callback. A first Passwordless login may create an Auth0 identity; until an authorized member assigns its role, Flowgency displays **Access pending**.

## 3. Permissions and roles

Create these API permissions:

| Permission | Purpose |
| --- | --- |
| `simulation:read` | Read-only live simulation access |
| `analytics:read` | Current-browser-session analytics |
| `simulation:control` | Start, pause, resume, reset, stop, and speed commands |

Create and assign roles exactly as follows:

| Role | Permissions |
| --- | --- |
| `analyst` | `simulation:read`, `analytics:read` |
| `operator` | `simulation:read`, `analytics:read`, `simulation:control` |

Operator is the administrator role for this MVP; do not create a separate application `admin` role. An operator may open Analyst pages because it has both read permissions. An analyst is rejected from Operator pages and FastAPI control endpoints.

## 4. Selective Operator MFA

Enable **Security > Multi-factor Auth > One-time Password** (TOTP/authenticator). Configure the tenant policy so the Post-Login Action below decides which users require MFA rather than forcing it for every analyst.

Create an Auth0 **Post Login** Action, deploy it, and add it to the Login flow:

```js
exports.onExecutePostLogin = async (event, api) => {
  if (event.user.app_metadata?.use_mfa === true) {
    api.multifactor.enable("any", {
      allowRememberBrowser: false,
    });
  }
};
```

For every operator, edit the user in the Dashboard and set application metadata:

```json
{
  "use_mfa": true
}
```

This must be `app_metadata`, which the end user cannot edit, never `user_metadata`. Do not enable `use_mfa` for analysts. `allowRememberBrowser: false` prevents the remembered-browser option from bypassing MFA on later interactive logins. Tenant configuration and user metadata are manual Dashboard tasks; the repository has no Management API credentials.

## 5. Local environment on each laptop

Copy `frontend/.env.example` to the ignored `frontend/.env.local`. Each teammate generates a different local cookie-encryption secret:

```bash
openssl rand -hex 32
```

Set the result as `AUTH0_SECRET`. The Auth0 application client secret is shared privately and is never committed. Keep the SDK v4 variable names shown in the example: `AUTH0_DOMAIN` contains no `https://`, while `APP_BASE_URL` is exactly:

```env
APP_BASE_URL=http://localhost:3000
```

Copy `backend/.env.example` to the ignored `backend/.env` (values in single quotes when they contain shell characters) or export the two values before startup. `AUTH0_DOMAIN` and `AUTH0_AUDIENCE` must exactly match the frontend and Dashboard API. No client secret is needed by FastAPI because it validates signed access tokens through the tenant's public JWKS.

Start the services from the repository root (activate the team's Python environment first):

```bash
set -a; source .env; source backend/.env; set +a   # also sets FLOWGENCY_ANALYTICS_DB if present
python -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8000
cd frontend
npm ci
npm run dev
```

`backend/.env` may also hold the team's `FLOWGENCY_ANALYTICS_DB` Postgres URL (shared by everyone, obtained privately). Without it the backend uses local SQLite at `data/analytics.sqlite3`. On Windows PowerShell, set variables with `$env:NAME = 'value'`. See `backend/README.md`.

The frontend uses `NEXT_PUBLIC_BACKEND_URL` for public GET/WebSocket traffic and server-only `BACKEND_URL` for the authenticated command proxy. Do not place tokens in browser storage.

## 6. Verification checklist

### Analyst account

1. Select **Continue as Analyst**, enter an email in Universal Login, and submit the emailed OTP.
2. Before role assignment, confirm **Access pending**.
3. Assign `analyst` in Auth0 and sign out/in so a new access token is issued.
4. Confirm `/analyst/simulation` and `/analyst/analytics` work, no controls are rendered, and `/operator` is denied.

### Operator account

1. Create/enable a database user, assign `operator`, and set `app_metadata.use_mfa=true`.
2. Select **Operator Secure Access**, authenticate with password, and enroll/verify TOTP.
3. Sign out and sign in again; confirm MFA is requested again and browser remembering is unavailable.
4. Confirm Operator Overview, Live Simulation, Analytics, and all control commands work.
5. Remove `simulation:control`, sign in again, and confirm both the Operator route and direct FastAPI POST return denial.

Public `/`, `/simulation`, read-only GET endpoints, and `/ws/simulation` remain available without authentication.

## 7. Troubleshooting

- **Callback URL mismatch:** ensure the application callback is exactly `http://localhost:3000/auth/callback`, including scheme and port. Restart Next.js after environment changes.
- **Configuration required:** create `frontend/.env.local` and provide every variable named on `/auth/configuration`. Never solve this by committing the file.
- **Invalid audience:** the Dashboard API identifier, frontend `AUTH0_AUDIENCE`, and backend `AUTH0_AUDIENCE` must be byte-for-byte identical. Auth0 SDK v4 receives audience through `Auth0Client.authorizationParameters`, not the removed v3 environment-only behavior.
- **Invalid issuer/JWKS:** `AUTH0_DOMAIN` must be the tenant domain without scheme. Confirm the backend can reach `https://<domain>/.well-known/jwks.json`.
- **Access pending:** authentication succeeded but the token has no Flowgency permissions. Assign a role, then sign out and sign in to mint a new token.
- **Access denied:** the token is valid but lacks a permission required by that workspace. Confirm role-to-permission assignments and **Add Permissions in the Access Token**.
- **401 from a command:** the token is absent, expired, malformed, has the wrong issuer/audience, or the Next.js session expired. Sign in again and inspect server logs.
- **403 from a command:** the access token is valid but lacks `simulation:control`.
- **Backend disconnected:** public and protected UI still render, but live data and commands require FastAPI on the configured URL.

## Dependency rationale

- `@auth0/nextjs-auth0` is Auth0's official Next.js App Router SDK; v4.33 supports Next.js 16 and provides encrypted sessions, Universal Login routes, and server token retrieval.
- `PyJWT[crypto]` verifies Auth0 RS256 signatures, JWKS keys, issuer, audience, and token lifetime in FastAPI. The JWKS client caches signing keys; tests inject a local key and never contact Auth0.
