# CEIR Workspace — Next.js

A clean Next.js rewrite of the supplied CEIR Electron interface. It uses a
persistent Playwright Chromium worker so CEIR requests run inside the
`ceir.gov.mm` origin with the browser's Cloudflare cookies.

## Run locally

```bash
npm install
npm run browser:install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Checks

```bash
npm run lint
npm run build
```

## First CEIR connection

1. Run the server from a Myanmar IP address and turn off foreign VPNs.
2. Keep `CEIR_HEADLESS=false` for the first run (the default).
3. Chromium opens `ceir.gov.mm`. Complete any Cloudflare screen manually.
4. The cookies persist in the private `.ceir-profile/` directory.
5. After a stable session is established, `CEIR_HEADLESS=true` may be used.

The browser worker serializes requests because ALTCHA tokens are one-time and
CEIR's payment chain must not overlap. The application never fabricates CEIR
results: connection, API, geo-block, and Cloudflare failures are returned to
the interface as errors.

For a remote deployment, the server hosting Chromium must still have a Myanmar
IP and a way for an operator to complete a renewed Cloudflare challenge.
