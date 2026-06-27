# D BOT Cyber Admin Redesign

This version removes the old inline admin website from the main `/admin` pages and replaces it with a modern exported Next.js dashboard.

## What changed

- New frontend rebuilt from scratch in `frontend/`.
- Stack: Next.js, React, Tailwind CSS, shadcn-style components, Recharts, Lucide icons, Framer Motion.
- Built static output is included in `frontend_out/` and served directly by FastAPI.
- Old FastAPI HTML admin pages were moved to `/admin-legacy/*`.
- Existing FastAPI admin APIs and actions remain available under `/admin/api/v2/*` and existing POST/GET action endpoints.
- Dockerfile now builds the frontend first and copies the exported output into the final Python image.

## Main URLs

- New dashboard: `/admin`
- Dashboard sections:
  - `/admin/plans`
  - `/admin/users`
  - `/admin/servers`
  - `/admin/categories`
  - `/admin/payments`
  - `/admin/discounts`
  - `/admin/resellers`
  - `/admin/orders-report`
  - `/admin/backup`
  - `/admin/settings`
- Login remains: `/login`
- Legacy pages remain available for emergency access: `/admin-legacy`

## Build locally

```bash
cd frontend
npm install
npm run build
cd ..
rm -rf frontend_out
cp -a frontend/out frontend_out
```

## Docker deploy

The root Dockerfile does the frontend build automatically:

```bash
docker compose build --no-cache api bot
docker compose up -d
```

Then open:

```text
https://YOUR_DOMAIN/admin
```

## Notes

The frontend reads real data from the existing FastAPI endpoints. If the session is expired, the UI shows a login-required screen and links to `/login`.
