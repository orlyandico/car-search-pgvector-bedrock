#!/usr/bin/env python3
"""
Helper script to connect to Aurora PostgreSQL using credentials from Secrets Manager.
Usage: ./scripts/psql.py [sql_file]
"""

import json
import os
import subprocess
import sys
import warnings

# Suppress all warnings including boto3 deprecation warnings
warnings.filterwarnings("ignore")

import boto3


def get_db_credentials():
    secrets = boto3.client("secretsmanager", region_name="eu-west-2")
    secret = secrets.get_secret_value(SecretId="car-search/db-credentials")
    return json.loads(secret["SecretString"])


def main():
    creds = get_db_credentials()

    env = os.environ.copy()
    env["PGPASSWORD"] = creds["password"]
    env["PGSSLMODE"] = "require"

    cmd = [
        "/usr/bin/psql",
        "-h",
        creds["host"],
        "-p",
        str(creds["port"]),
        "-U",
        creds["username"],
        "-d",
        creds["database"],
    ]

    # If SQL file provided, execute it
    if len(sys.argv) > 1:
        cmd.extend(["-f", sys.argv[1]])

    subprocess.run(cmd, env=env)


if __name__ == "__main__":
    main()
