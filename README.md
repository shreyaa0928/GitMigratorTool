# Git Migrator Tool ⚡

A comprehensive web application to migrate complete VCS systems between providers — **GitHub ↔ GitLab** — with support for full sync, scheduled sync, and selective migration of branches, tags, issues, PRs, and collaborators.


---

## ✨ Features

| Feature | Description |
|---|---|
| **Multi-Provider** | GitHub, GitLab (all combinations) |
| **Manual Full Sync** | One-click full repository migration |
| **Scheduled Sync** | Interval-based or cron-based automatic sync |
| **Selective Migration** | Choose exactly what to migrate |
| **Real-time Progress** | Live job status polling with step-by-step updates |
| **Migration History** | Persistent SQLite-backed history |
| **Repo Browser** | Browse & select repositories via token |

### What can be migrated

- ✅ Repository (metadata, description, visibility)
- ✅ All Branches
- ✅ Specific Branches (select by name)
- ✅ Tags
- ✅ Issues (with labels)
- ✅ Pull Requests / Merge Requests
- ✅ Collaborators / Team Members

---

## 🏗 Architecture

```
VCS Migrator Pro
├── frontend/
│   └── index.html          # Single-page app (HTML/CSS/JS)
├── backend/
│   ├── app.py              # Flask REST API
│   ├── db.py               # SQLite migration history
│   ├── scheduler.py        # APScheduler for scheduled sync
│   └── migrators/
│       ├── base.py         # Abstract base class
│       ├── github.py       # GitHub REST API v3
│       └── gitlab.py       # GitLab REST API v4
```

### API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | Health check |
| POST | `/api/repos` | List repos for a provider+token |
| POST | `/api/migrate` | Start migration job (async) |
| GET | `/api/migrate/:id/status` | Poll job status |
| POST | `/api/schedule` | Create scheduled sync |
| GET | `/api/schedule` | List all schedules |
| DELETE | `/api/schedule/:id` | Delete a schedule |
| GET | `/api/history` | Migration history |

### Migration flow

```
User → POST /api/migrate
         ↓
     job_id returned immediately (async)
         ↓
     Background thread runs migration:
       1. Fetch source repo info
       2. Create target repo
       3. Clone & push branches (git mirror)
       4. Push tags
       5. Create issues via API
       6. Create PRs via API
       7. Add collaborators
         ↓
     GET /api/migrate/:id/status (polled every 1.2s)
         ↓
     Results stored in SQLite
```

---

## 🚀 Local Setup

### Backend

```bash
cd backend
pip install -r requirements.txt
python app.py
```

### Frontend

The frontend is a static HTML file — open directly or serve with any web server:

```bash
cd frontend
python -m http.server 8080
```

Or use VS Code Live Server.

---

## 🔑 Token Permissions

### GitHub
Create at **Settings → Developer settings → Personal access tokens**

Required scopes: `repo`, `read:org`, `write:repo_hook`

### GitLab
Create at **User Settings → Access Tokens**

Required scopes: `api`, `read_repository`, `write_repository`

---

## 📋 Usage Guide

### 1. Manual Migration
1. Select source provider (GitHub/GitLab)
2. Enter source access token
3. Click **Browse** to pick a repository, or type `owner/repo`
4. Do the same for target
5. Choose what to migrate (branches, tags, issues, PRs, collaborators)
6. For specific branches: check **Specific Branches** and type branch names
7. Click **⚡ Start Migration**
8. Watch real-time progress

### 2. Scheduled Sync
1. Go to **Scheduled Sync** tab
2. Set interval (1h, 6h, 12h, 24h, weekly, or custom cron)
3. Enter source and target in format `provider:owner/repo`
4. Enter both tokens
5. Click **Create Schedule**

### 3. Migration History
- View all past migrations in the **History** tab
- See source/target, status, and timestamp

---

## 🔧 Extending

To add a new provider (e.g. Azure DevOps):

1. Create `backend/migrators/azure.py` extending `BaseMigrator`
2. Implement all abstract methods
3. Register in `app.py`:
   ```python
   from migrators.azure import AzureDevOpsMigrator
   PROVIDER_MAP["azure"] = AzureDevOpsMigrator
   ```
4. Add provider button in `frontend/index.html`

---

## 📄 License

MIT — free to use and modify.
