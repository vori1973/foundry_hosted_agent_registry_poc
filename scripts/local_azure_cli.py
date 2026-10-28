#!/usr/local/bin/python
"""Local-test-only AzureCliCredential adapter; never include in the agent image."""

import argparse
import json
import sys
import time
from pathlib import Path


RESOURCE = "https://ai.azure.com"
TOKEN_FILE = Path("/run/poc-identity/token.json")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["account"])
    parser.add_argument("operation", choices=["get-access-token"])
    parser.add_argument("--resource", required=True, choices=[RESOURCE])
    parser.add_argument("--output", required=True, choices=["json"])
    parser.parse_args(argv)
    try:
        token = json.loads(TOKEN_FILE.read_text())
        if (
            not isinstance(token["accessToken"], str)
            or not token["accessToken"]
            or not time.time() + 30 < token["expires_on"] <= time.time() + 7200
        ):
            raise ValueError("Invalid local token.")
        print(json.dumps({"accessToken": token["accessToken"], "expires_on": token["expires_on"]}))
    except (OSError, ValueError, TypeError, KeyError):
        print("Local test identity is unavailable or expired.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
