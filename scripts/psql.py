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
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    secrets = boto3.client("secretsmanager", region_name=region)
    
    response = secrets.list_secrets(Filters=[{'Key': 'name', 'Values': ['car-search/db-credentials-']}])
    if not response['SecretList']:
        raise Exception('No secret found with prefix car-search/db-credentials-')
    
    secret = secrets.get_secret_value(SecretId=response['SecretList'][0]['ARN'])
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
        sql_file = os.path.realpath(sys.argv[1])
        if not os.path.isfile(sql_file):
            print(f"Error: {sys.argv[1]} is not a valid file", file=sys.stderr)
            sys.exit(1)
        cmd.extend(["-f", sql_file])

    subprocess.run(cmd, env=env)  # nosemgrep: dangerous-subprocess-use-audit


if __name__ == "__main__":
    main()
