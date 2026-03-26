# Architecture & Design Document — VCS Migrator Pro

## 1. Overview

VCS Migrator Pro is a web application that enables complete migration of Version Control System (VCS) repositories between major providers: **GitHub**, **GitLab**, and **Bitbucket**.

It supports both one-time migrations and scheduled/automated syncs.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Browser (User)                        │
│  ┌──────────────────────────────────────────────────┐   │
│  │           Frontend (Static HTML/JS/CSS)           │   │
│  │   • Provider Selection   • Options Grid           │   │
│  │   • Repo Browser         • Progress Polling       │   │
│  │   • Schedule Manager     • Migration History      │   │
│  └──────────────────────────┬───────────────────────┘   │
└─────────────────────────────┼───────────────────────────┘
                              │ REST API (JSON)
┌─────────────────────────────▼───────────────────────────┐
│                 Backend (Flask API)                       │
│                                                           │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  app.py      │  │ scheduler.py │  │    db.py      │  │
│  │  REST Routes │  │ APScheduler  │  │ SQLite Store  │  │
│  └──────┬───────┘  └──────┬───────┘  └───────────────┘  │
│         │                 │                               │
│  ┌──────▼─────────────────▼───────────────────────────┐  │
│  │           Migration Engine (Thread Pool)            │  │
│  └──────┬──────────────┬────────────────┬─────────────┘  │
│         │              │                │                 │
│  ┌──────▼──────┐ ┌─────▼──────┐ ┌──────▼──────────┐     │
│  │  GitHub     │ │  GitLab    │ │  Bitbucket      │     │
│  │  Migrator   │ │  Migrator  │ │  Migrator       │     │
│  └──────┬──────┘ └─────┬──────┘ └──────┬──────────┘     │
└─────────┼──────────────┼───────────────┼─────────────────┘
          │              │               │
  ┌───────▼──────────────▼───────────────▼───────────┐
  │           External VCS APIs                        │
  │   GitHub REST API v3  │  GitLab API v4            │
  │   Bitbucket Cloud API 2.0  │  git clone/push      │
  └──────────────────────────────────────────────────┘
```

---

## 3. Component Details

### 3.1 Frontend (frontend/index.html)

**Single-page application** built with plain HTML, CSS, and vanilla JavaScript.

Key sections:
- **Migrate tab**: Provider selection, token input, repository browser, options grid, progress tracking
- **Schedule tab**: Create/manage automated sync schedules
- **History tab**: View past migrations from the server

State management: DOM-based state with fetch API for backend communication.

Progress polling: `setInterval` every 1.2 seconds polling `/api/migrate/:id/status` until job completes.

### 3.2 Backend (Flask REST API)

**app.py** — Main entry point:
- Registers REST routes
- Spawns background threads for migrations (one thread per job)
- Maintains in-memory `migration_jobs` dict for live status
- Delegates to provider-specific migrator classes

**Async job pattern:**
```
POST /api/migrate
   → generates job_id
   → starts daemon thread
   → returns {job_id} immediately

GET /api/migrate/:id/status
   → returns current status, progress %, step name, results
```

### 3.3 Migrator Classes (migrators/)

Each provider has its own class implementing `BaseMigrator`:

| Class | API Used | Auth |
|---|---|---|
| `GitHubMigrator` | GitHub REST API v3 | Personal Access Token |
| `GitLabMigrator` | GitLab REST API v4 | Private Token |
| `BitBucketMigrator` | Bitbucket Cloud API 2.0 | Bearer Token |

**BaseMigrator** defines the contract:
```python
list_repositories()       → List repos for the account
get_repository_info()     → Get metadata of one repo
get_branches()            → List all branches
get_specific_branches()   → Filter branches by name
get_tags()                → List all tags
get_issues()              → List all issues
get_pull_requests()       → List all PRs/MRs
get_collaborators()       → List collaborators
create_repository()       → Create repo on target
push_branches()           → git clone --mirror + push
push_tags()               → git push --tags
create_issues()           → Create issues via API
create_pull_requests()    → Create PRs via API
add_collaborators()       → Add team members
```

**Git operations** (push_branches, push_tags) use a `git clone --mirror` into a `tempfile.TemporaryDirectory()` then `git push` with the target's authenticated URL. This ensures all refs are transferred faithfully.

### 3.4 Scheduler (scheduler.py)

Uses **APScheduler BackgroundScheduler** with:
- `IntervalTrigger` for minute-based schedules
- `CronTrigger.from_crontab()` for custom cron expressions

Each schedule stores its payload (source/target provider, tokens, repo names, options) and triggers a migration job automatically.

### 3.5 Database (db.py)

**SQLite** via Python's built-in `sqlite3` module.

Table: `migrations`
```sql
CREATE TABLE migrations (
    id TEXT PRIMARY KEY,
    source_provider TEXT,
    target_provider TEXT,
    source_repo TEXT,
    target_repo TEXT,
    status TEXT,        -- queued | running | completed | failed
    results TEXT,       -- JSON blob
    created_at TEXT,
    completed_at TEXT
)
```

---

## 4. Migration Flow (Detailed)

```
1. User selects source provider + enters token
2. User browses/selects source repository
3. User selects target provider + enters token
4. User enters target repo name
5. User selects options (branches, tags, issues, PRs, users)
6. Click "Start Migration"

→ Frontend: POST /api/migrate with full payload
→ Backend: Generates job_id, starts daemon thread
→ Frontend: Begins polling /api/migrate/{job_id}/status every 1.2s

Background thread:
  Step 1: Instantiate source + target migrator classes
  Step 2: source.get_repository_info() → target.create_repository()
  Step 3 (if branches): source.get_branches() → target.push_branches()
  Step 4 (if specific_branches): source.get_specific_branches(names) → push
  Step 5 (if tags): source.get_tags() → target.push_tags()
  Step 6 (if issues): source.get_issues() → target.create_issues()
  Step 7 (if pull_requests): source.get_pull_requests() → target.create_pull_requests()
  Step 8 (if users): source.get_collaborators() → target.add_collaborators()

  Each step updates progress% and current_step in migration_jobs dict

  On completion: save to SQLite via db.save_migration()

→ Frontend poll detects status=completed → shows results grid
```

---

## 5. Security Considerations

- **Tokens are never stored** — they are passed in the request and used only during the migration job. They exist in memory only during the job's lifetime.
- **HTTPS required** — deploy backend behind HTTPS (Render/Railway provide this)
- **CORS** — flask-cors allows frontend origin
- **No token logging** — tokens are excluded from logs

---

## 6. Supported Migration Paths

| Source | Target | Status |
|---|---|---|
| GitHub | GitLab | ✅ Full support |
| GitHub | Bitbucket | ✅ Full support |
| GitLab | GitHub | ✅ Full support |
| GitLab | Bitbucket | ✅ Full support |
| Bitbucket | GitHub | ✅ Full support |
| Bitbucket | GitLab | ✅ Full support |
| GitHub | GitHub | ✅ Fork/Copy |

---

## 7. Technology Stack

| Layer | Technology |
|---|---|
| Frontend | HTML5, CSS3, Vanilla JS |
| Backend | Python 3.10+, Flask 3.x |
| HTTP Client | requests |
| Scheduler | APScheduler 3.x |
| Database | SQLite (built-in) |
| Git ops | subprocess + git CLI |
| Deployment (BE) | Gunicorn, Render/Railway |
| Deployment (FE) | Vercel/Netlify (static) |
