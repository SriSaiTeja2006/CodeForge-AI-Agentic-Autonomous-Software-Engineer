"""
CodeForge AI Background Worker
Run locally with:
    python -m app.worker
"""
import logging
import signal
import sys
from app.services.task_runner import get_task_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("codeforge.worker")


def main():
    logger.info("Initializing CodeForge AI background worker...")
    worker = get_task_worker()

    def handle_signal(sig, frame):
        logger.info("Shutdown signal received (%s). Stopping worker gracefully...", sig)
        worker.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    logger.info("Worker started. Listening for queued tasks in PostgreSQL...")
    worker.run_worker_loop()


if __name__ == "__main__":
    main()
