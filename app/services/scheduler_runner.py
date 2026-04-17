"""バックグラウンドで schedule_worker を定期的に起動する。"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask

logger = logging.getLogger(__name__)
_started = False
_lock = threading.Lock()


def _loop(app: "Flask") -> None:
    poll = float(app.config.get("SD_SCHEDULER_POLL_SECONDS") or 60.0)
    poll = max(15.0, min(poll, 3600.0))
    logger.info("SD scheduler loop started (poll=%ss)", poll)
    while True:
        time.sleep(poll)
        try:
            with app.app_context():
                from app.services import schedule_worker

                n = schedule_worker.run_due_jobs()
                if n:
                    logger.info("SD scheduler: processed %s job(s)", n)
        except Exception:
            logger.exception("SD scheduler tick failed")


def start_background_scheduler(app: "Flask") -> None:
    """デーモンスレッドで run_due_jobs を繰り返す（多重起動しない）。"""
    global _started
    with _lock:
        if _started:
            return
        if not app.config.get("SD_SCHEDULER_ENABLED"):
            return
        t = threading.Thread(target=_loop, args=(app,), daemon=True, name="sd-scheduler")
        t.start()
        _started = True
        logger.info("SD background scheduler thread started")
