"""Version 1 JSON-lines replay protocol; stdout contains protocol messages only."""

import json
import logging
import sys

from payops.lab.replay import replay_trace


def main():
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, force=True)
    for line in sys.stdin:
        try:
            if len(line) > 8192:
                raise ValueError("Replay request too large")
            request = json.loads(line)
            if request.get("protocol") != 1:
                raise ValueError("Unsupported replay protocol")
            result = replay_trace(request["actions"], request["mutation"])
            response = {"protocol": 1, "result": result}
        except (ValueError, KeyError, TypeError) as exc:
            response = {"protocol": 1, "error": str(exc)}
        except Exception:
            logging.exception("Replay worker failed")
            response = {"protocol": 1, "error": "Replay worker failed; inspect stderr"}
        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
