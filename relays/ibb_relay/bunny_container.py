"""Print the Bunny Magic Containers template that runs server.py on the stock Python image."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SERVER = Path(__file__).with_name("server.py")
PORT = 8080


def container_template(token: str) -> dict:
    health = {"httpGet": {"request": {"path": "/healthz", "portNumber": PORT}}, "periodSeconds": 30, "failureThreshold": 3}
    return {
        "name": "ibb-relay",
        "imageRegistryId": "1155",
        "imageNamespace": "library",
        "imageName": "python",
        "imageTag": "3.12-alpine",
        "imagePullPolicy": "ifNotPresent",
        "entryPoint": {"commandArray": ["python"], "argumentsArray": ["-c", SERVER.read_text()]},
        "environmentVariables": [{"name": "RELAY_TOKEN", "value": token}, {"name": "PORT", "value": str(PORT)}],
        "probes": {"readiness": health, "liveness": health},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", type=Path, required=True)
    token = parser.parse_args().token_file.read_text().strip()
    if len(token) < 32:
        raise SystemExit("relay token must be at least 32 characters")
    print(json.dumps(container_template(token)))


if __name__ == "__main__":
    main()
