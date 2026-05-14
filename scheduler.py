"""
Scheduler
=========
APScheduler-based periodic task runner.
Triggers the full pipeline (scan -> dedup -> test -> filter -> generate)
on a configurable interval.
"""

import logging
import threading
import time
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from config import UPDATE_INTERVAL_HOURS, UPDATE_CRON

logger = logging.getLogger("scheduler")

TZ_CN = timezone(timedelta(hours=8))


class IPTVScheduler:
    """Manages periodic execution of the IPTV pipeline."""

    def __init__(self, pipeline_func, server_update_func=None):
        """
        Args:
            pipeline_func: async or sync function that runs the full pipeline.
            server_update_func: function to update server stats after pipeline.
        """
        self.pipeline_func = pipeline_func
        self.server_update_func = server_update_func
        self.scheduler = BackgroundScheduler(
            timezone=TZ_CN,
            job_defaults={
                "coalesce": True,          # skip missed runs
                "max_instances": 1,        # only one instance at a time
                "misfire_grace_time": 300,  # 5 min grace
            },
        )
        self._running = False
        self._pipeline_thread = None

    def _run_pipeline_sync(self):
        """Run the pipeline in a thread (pipeline_func may be async)."""
        import asyncio

        logger.info("Pipeline run starting...")
        start_time = time.monotonic()

        # Mark as running in server stats
        if self.server_update_func:
            self.server_update_func({"pipeline_running": True})

        try:
            if asyncio.iscoroutinefunction(self.pipeline_func):
                loop = asyncio.new_event_loop()
                try:
                    result = loop.run_until_complete(self.pipeline_func())
                finally:
                    loop.close()
            else:
                result = self.pipeline_func()

            elapsed = time.monotonic() - start_time
            logger.info(f"Pipeline completed in {elapsed:.1f}s")

            if self.server_update_func and result:
                now = datetime.now(TZ_CN).strftime("%H:%M")
                next_time = datetime.now(TZ_CN) + timedelta(hours=UPDATE_INTERVAL_HOURS)
                self.server_update_func({
                    "last_update": now,
                    "total_channels": result.get("total_scanned", 0),
                    "alive_channels": result.get("alive", 0),
                    "scan_duration": round(elapsed, 1),
                    "next_update": next_time.strftime("%H:%M"),
                    "update_interval_hours": UPDATE_INTERVAL_HOURS,
                    "pipeline_running": False,
                })

        except Exception as e:
            logger.error(f"Pipeline failed: {e}", exc_info=True)
            if self.server_update_func:
                self.server_update_func({"pipeline_running": False})

    def run_now(self):
        """Trigger an immediate pipeline run (non-blocking)."""
        self._pipeline_thread = threading.Thread(
            target=self._run_pipeline_sync,
            daemon=True,
        )
        self._pipeline_thread.start()

    def start(self, run_immediately: bool = True):
        """
        Start the scheduler.
        Args:
            run_immediately: If True, run the pipeline once immediately.
        """
        if self._running:
            logger.warning("Scheduler is already running")
            return

        # Configure trigger
        if UPDATE_CRON:
            trigger = CronTrigger.from_crontab(UPDATE_CRON, timezone=TZ_CN)
            logger.info(f"Scheduling with cron: {UPDATE_CRON}")
        else:
            trigger = IntervalTrigger(
                hours=UPDATE_INTERVAL_HOURS,
                timezone=TZ_CN,
            )
            logger.info(f"Scheduling every {UPDATE_INTERVAL_HOURS} hours")

        # Add job
        self.scheduler.add_job(
            self._run_pipeline_sync,
            trigger=trigger,
            id="iptv_pipeline",
            name="IPTV Pipeline",
            replace_existing=True,
        )

        self.scheduler.start()
        self._running = True

        # Next run time
        job = self.scheduler.get_job("iptv_pipeline")
        if job and job.next_run_time:
            next_run = job.next_run_time.astimezone(TZ_CN).strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f"Next scheduled run: {next_run}")

        # Run immediately
        if run_immediately:
            logger.info("Running initial pipeline now...")
            self.run_now()

    def stop(self):
        """Stop the scheduler."""
        if self._running:
            self.scheduler.shutdown(wait=False)
            self._running = False
            logger.info("Scheduler stopped")

    def get_status(self) -> dict:
        """Get current scheduler status."""
        job = self.scheduler.get_job("iptv_pipeline") if self._running else None
        return {
            "running": self._running,
            "next_run": (
                job.next_run_time.astimezone(TZ_CN).strftime("%Y-%m-%d %H:%M:%S")
                if job and job.next_run_time else "N/A"
            ),
            "interval_hours": UPDATE_INTERVAL_HOURS,
        }