#!/usr/bin/env python3
"""Dog-in-zone detector entry point: logging setup + Supervisor().run().

The per-frame pipeline lives in worker.py (one CameraWorker per camera) and the
shared services + thread lifecycle in supervisor.py.
"""

import logging
import signal
import sys

from core.supervisor import Supervisor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("werkzeug").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("detector")


def main():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    log.info("===== DOG DETECTOR STARTING =====")
    Supervisor().run()


if __name__ == "__main__":
    main()
