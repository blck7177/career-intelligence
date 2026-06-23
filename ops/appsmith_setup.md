# Appsmith Ops Console Setup

No code changes are required for P0-7. This is a configuration task.

## Prerequisites

P0-6 must be deployed first so `/api/admin/*` endpoints are live.

## Step 1 — Promote yourself to admin

Connect to Postgres and run:

```sql
UPDATE users SET is_admin = true WHERE email = 'your@email.com';
```

Verify:

```sql
SELECT id, email, is_admin FROM users;
```

## Step 2 — Get a long-lived admin Bearer token

Option A (easiest for local testing): Log in to the frontend as your admin account,
open browser DevTools → Application → Cookies or Network, and copy the Clerk
`__session` Bearer token from any `/api/app/*` request header.

Option B: In the Clerk dashboard, create a JWT template with no expiry and
generate a machine token for ops tooling.

## Step 3 — Create Appsmith app

1. Go to https://app.appsmith.com (or your self-hosted Appsmith instance)
2. Create a new app → "Blank"
3. Add a REST API datasource:
   - Name: `Career OpenClaw Admin`
   - URL: `https://your-api-domain.com` (or `http://localhost:8000` for local)
   - Headers: `Authorization: Bearer <your-admin-token>`

## Step 4 — Create pages

### Runs page

Query: `GET {{Career_OpenClaw_Admin.url}}/api/admin/runs?limit=100`

Table columns: `id`, `workspace_id`, `run_type`, `status`, `created_at`

Add a "View Tasks" button that queries:
`GET /api/admin/runs/{{runs_table.selectedRow.id}}/tasks`

Add a "View Events" button that queries:
`GET /api/admin/runs/{{runs_table.selectedRow.id}}/events`

Add a "View Invocations" button that queries:
`GET /api/admin/runs/{{runs_table.selectedRow.id}}/agent-invocations`

Add a "Cancel" button (POST):
`POST /api/admin/runs/{{runs_table.selectedRow.id}}/cancel`

### Users page

Query: `GET /api/admin/users`
Table columns: `id`, `email`, `is_admin`, `created_at`

### Workspaces page

Query: `GET /api/admin/workspaces`
Table columns: `id`, `name`, `created_at`

## Step 5 — Filter runs by workspace

On the Runs page, add an Input widget `workspaceFilter` and wire the query to:
`GET /api/admin/runs?workspace_id={{workspaceFilter.text}}&limit=100`
