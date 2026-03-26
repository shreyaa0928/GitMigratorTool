"""Scheduled migration support using APScheduler."""
import uuid
import threading
from datetime import datetime

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False


class MigrationScheduler:
    def __init__(self, db):
        self.db = db
        self.schedules = {}
        if SCHEDULER_AVAILABLE:
            self.scheduler = BackgroundScheduler()
        else:
            self.scheduler = None

    def start(self):
        if self.scheduler:
            self.scheduler.start()

    def add_schedule(self, data: dict) -> str:
        schedule_id = str(uuid.uuid4())
        interval_minutes = data.get("interval_minutes", 60)
        cron = data.get("cron")  # optional cron string
        payload = data.get("migration_payload", {})

        self.schedules[schedule_id] = {
            "id": schedule_id,
            "interval_minutes": interval_minutes,
            "cron": cron,
            "payload": payload,
            "created_at": datetime.utcnow().isoformat(),
            "last_run": None,
            "next_run": None,
            "enabled": True,
        }

        if self.scheduler:
            def run_job():
                from app import run_migration_job, migration_jobs
                job_id = str(uuid.uuid4())
                migration_jobs[job_id] = {
                    "job_id": job_id, "status": "queued", "progress": 0,
                    "current_step": "Scheduled run", "created_at": datetime.utcnow().isoformat(),
                    "results": {}, "error": None,
                }
                t = threading.Thread(target=run_migration_job, args=(job_id, payload), daemon=True)
                t.start()
                self.schedules[schedule_id]["last_run"] = datetime.utcnow().isoformat()

            if cron:
                trigger = CronTrigger.from_crontab(cron)
            else:
                trigger = IntervalTrigger(minutes=interval_minutes)

            job = self.scheduler.add_job(run_job, trigger, id=schedule_id)
            next_run = job.next_run_time
            if next_run:
                self.schedules[schedule_id]["next_run"] = next_run.isoformat()

        return schedule_id

    def remove_schedule(self, schedule_id: str):
        self.schedules.pop(schedule_id, None)
        if self.scheduler:
            try:
                self.scheduler.remove_job(schedule_id)
            except Exception:
                pass

    def list_schedules(self) -> list:
        return list(self.schedules.values())
