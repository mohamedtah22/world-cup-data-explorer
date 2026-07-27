# Render Deployment Guide

This project is deployable as three Render resources from GitHub:

- Render PostgreSQL: `world-cup-postgres`
- Flask Web Service: `world-cup-api`
- React Static Site: `world-cup-frontend`

The Flask/Gunicorn app does not initialize or reset the database at startup. Database loading is an explicit one-time operation.

## 1. Push to GitHub

Commit the deployment changes, then push the repository to GitHub. Do not commit real `.env` files.

## 2. Create the Render Blueprint

1. In Render, choose **New** then **Blueprint**.
2. Connect the GitHub repository.
3. Select the root-level `render.yaml`.
4. Review the three resources before applying:
   - `world-cup-postgres`
   - `world-cup-api`
   - `world-cup-frontend`

## 3. Configure Environment Variables

The Blueprint wires `DATABASE_URL` for the API from `world-cup-postgres`.

Backend service `world-cup-api`:

```text
DATABASE_URL=<set by Render from world-cup-postgres>
FRONTEND_ORIGINS=https://world-cup-frontend.onrender.com
```

Frontend static site `world-cup-frontend`:

```text
VITE_API_URL=https://world-cup-api-0elm.onrender.com/api
```

If Render assigns different service URLs or you use custom domains, update `FRONTEND_ORIGINS` and `VITE_API_URL` in the Render dashboard and redeploy the affected service.

## 4. Deploy Services

Render will build the API with:

```bash
pip install -r backend/requirements.txt
```

Render will start the API with:

```bash
gunicorn --chdir backend --bind 0.0.0.0:$PORT app:app
```

Render will build the frontend from the `frontend` root directory with:

```bash
npm ci && npm run build
```

The static publish directory is `dist`, and the Blueprint rewrites `/*` to `/index.html` for SPA routing.

## 5. Initialize the Database Once

After PostgreSQL and the API environment are available, run the initial database load from a local terminal or a controlled Render shell with `DATABASE_URL` set to the Render PostgreSQL connection string:

```bash
python scripts/deploy_database.py --initial-load
```

The command refuses to load into a non-empty database. To intentionally delete and reload existing production data, use:

```bash
python scripts/deploy_database.py --force-reset
```

Use `--force-reset` only after taking any needed backups.

## 6. Test the Live App

Check the API:

```text
https://world-cup-api-0elm.onrender.com/health
https://world-cup-api-0elm.onrender.com/api/dashboard
```

Expected health response:

```json
{
  "status": "ok",
  "database": "connected"
}
```

Open:

```text
https://world-cup-frontend.onrender.com
```

Verify:

- Overview loads dashboard counts.
- Player Compare autocomplete can find `Lionel Messi` and `Harry Kane`.
- Team Compare autocomplete can find `Argentina`.
- Data Quality shows source coverage.
