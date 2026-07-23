import signal
import threading

import dotenv

from agent.intelligence.service import IntelligenceService


def main():
    dotenv.load_dotenv()
    service = IntelligenceService.from_env()

    if not service.enabled:
        raise SystemExit(
            "World intelligence is disabled. Set "
            "ENTITY_INTELLIGENCE_ENABLED=true."
        )

    stopped = threading.Event()

    def request_stop(*_):
        stopped.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    service.start()

    try:
        stopped.wait()
    finally:
        service.stop()


if __name__ == "__main__":
    main()
