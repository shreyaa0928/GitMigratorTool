from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import threading
import uuid
from datetime import datetime
from migrators.github import GitHubMigrator
from migrators.gitlab import GitLabMigrator
from migrators.bitbucket import BitBucketMigrator
from scheduler import MigrationScheduler
from db import MigrationDB
 
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=False)
 
db = MigrationDB()
scheduler = MigrationScheduler(db)
 
PROVIDER_MAP = {
    "github": GitHubMigrator,
    "gitlab": GitLabMigrator,
    "bitbucket": BitBucketMigrator,
}
 
migration_jobs = {}  # job_id -> status dict
 
 
def run_migration_job(job_id, payload):
    source_provider = payload["source_provider"]
    target_provider = payload["target_provider"]
    source_token = payload["source_token"]
    target_token = payload["target_token"]
    source_repo = payload["source_repo"]
    target_repo = payload["target_repo"]
    options = payload.get("options", {})
 
    migration_jobs[job_id]["status"] = "running"
    migration_jobs[job_id]["started_at"] = datetime.utcnow().isoformat()
    results = {}
 
    try:
        SourceClass = PROVIDER_MAP.get(source_provider)
        TargetClass = PROVIDER_MAP.get(target_provider)
        if not SourceClass or not TargetClass:
            raise ValueError(f"Unsupported provider: {source_provider} or {target_provider}")
 
        source = SourceClass(source_token, source_repo)
        target = TargetClass(target_token, target_repo)
 
        steps = []
        if options.get("repository", True):
            steps.append(("repository", "Migrating repository info"))
        if options.get("branches"):
            steps.append(("branches", "Migrating branches"))
        if options.get("specific_branches"):
            steps.append(("specific_branches", "Migrating selected branches"))
        if options.get("tags"):
            steps.append(("tags", "Migrating tags"))
        if options.get("issues"):
            steps.append(("issues", "Migrating issues"))
        if options.get("pull_requests"):
            steps.append(("pull_requests", "Migrating pull requests"))
        if options.get("users"):
            steps.append(("users", "Migrating collaborators"))
 
        total = len(steps)
        migration_jobs[job_id]["total_steps"] = total
 
        for idx, (step_key, step_label) in enumerate(steps):
            migration_jobs[job_id]["current_step"] = step_label
            migration_jobs[job_id]["progress"] = int((idx / total) * 100)
 
            if step_key == "repository":
                results["repository"] = target.create_repository(source.get_repository_info())
            elif step_key == "branches":
                branch_list = source.get_branches()
                results["branches"] = target.push_branches(branch_list, source.clone_url)
            elif step_key == "specific_branches":
                selected = options.get("branch_names", [])
                branch_list = source.get_specific_branches(selected)
                results["specific_branches"] = target.push_branches(branch_list, source.clone_url)
            elif step_key == "tags":
                tags = source.get_tags()
                results["tags"] = target.push_tags(tags, source.clone_url)
            elif step_key == "issues":
                issues = source.get_issues()
                results["issues"] = target.create_issues(issues)
            elif step_key == "pull_requests":
                prs = source.get_pull_requests()
                results["pull_requests"] = target.create_pull_requests(prs)
            elif step_key == "users":
                users = source.get_collaborators()
                results["users"] = target.add_collaborators(users)
 
        migration_jobs[job_id]["status"] = "completed"
        migration_jobs[job_id]["progress"] = 100
        migration_jobs[job_id]["results"] = results
        migration_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()
        db.save_migration(job_id, payload, "completed", results)
 
    except Exception as e:
        migration_jobs[job_id]["status"] = "failed"
        migration_jobs[job_id]["error"] = str(e)
        migration_jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()
        db.save_migration(job_id, payload, "failed", {"error": str(e)})
 
 
@app.route("/api/health")
def health():
    return jsonify({"status": "OK", "timestamp": datetime.utcnow().isoformat()})
 
 
@app.route("/api/repos", methods=["POST"])
def list_repos():
    """List repositories from a provider given a token."""
    data = request.get_json()
    provider = data.get("provider", "").lower()
    token = data.get("token", "")
    try:
        Cls = PROVIDER_MAP.get(provider)
        if not Cls:
            return jsonify({"error": "Unknown provider"}), 400
        m = Cls(token, "")
        repos = m.list_repositories()
        return jsonify({"repos": repos})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
 
 
@app.before_request
def log_request_info():
    print(f"REQUEST: {request.method} {request.path}")
    if request.is_json:
        print(f"PAYLOAD: {request.json}")

@app.route("/api/migrate", methods=["POST"])
def start_migration():
    payload = request.get_json()
    print(f"DEBUG: Starting migration job for {payload.get('source_repo')} -> {payload.get('target_repo')}")
    job_id = str(uuid.uuid4())
    migration_jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "progress": 0,
        "current_step": "Queued",
        "created_at": datetime.utcnow().isoformat(),
        "results": {},
        "error": None,
    }
    t = threading.Thread(target=run_migration_job, args=(job_id, payload), daemon=True)
    t.start()
    return jsonify({"job_id": job_id, "status": "queued"})
 
 
@app.route("/api/migrate/<job_id>/status")
def migration_status(job_id):
    job = migration_jobs.get(job_id)
    if not job:
        saved = db.get_migration(job_id)
        if saved:
            return jsonify(saved)
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)
 
 
@app.route("/api/schedule", methods=["POST"])
def create_schedule():
    data = request.get_json()
    schedule_id = scheduler.add_schedule(data)
    return jsonify({"schedule_id": schedule_id, "status": "scheduled"})
 
 
@app.route("/api/schedule", methods=["GET"])
def list_schedules():
    return jsonify({"schedules": scheduler.list_schedules()})
 
 
@app.route("/api/schedule/<schedule_id>", methods=["DELETE"])
def delete_schedule(schedule_id):
    scheduler.remove_schedule(schedule_id)
    return jsonify({"status": "deleted"})
 
 
@app.route("/api/history")
def migration_history():
    history = db.get_all_migrations()
    return jsonify({"history": history})
 
 
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    scheduler.start()
    print(f"Git Migrator Pro running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
