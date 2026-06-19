#!/usr/bin/env python3
"""Ensure the 'svix' database exists, creating it if necessary.

Runs before migrations so that svix-server can connect on first deploy.
Uses autocommit because CREATE DATABASE cannot run inside a transaction.
"""

import psycopg
import psycopg.errors

from app.config import settings


def create_svix_db() -> None:
    dsn = (
        f"host={settings.db_host} "
        f"port={settings.db_port} "
        f"dbname={settings.db_name} "
        f"user={settings.db_user} "
        f"password={settings.db_password.get_secret_value()}"
    )
    print(
        f"Connecting to Postgres host={settings.db_host} port={settings.db_port} "
        f"dbname={settings.db_name} user={settings.db_user}"
    )
    with psycopg.connect(dsn, autocommit=True) as conn:
        print("Connected. Checking for 'svix' database...")
        # Check existence first. Postgres checks the CREATEDB privilege *before*
        # checking whether the target database exists, so attempting CREATE on a
        # limited user raises InsufficientPrivilege even when 'svix' is present.
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = 'svix'"
        ).fetchone()
        if exists:
            print("Svix database already exists, skipping.")
            return
        print("Svix database not found, attempting to create it...")
        try:
            conn.execute("CREATE DATABASE svix")
            print("✓ Created 'svix' database.")
        except psycopg.errors.DuplicateDatabase:
            print("Svix database already exists, skipping.")
        except psycopg.errors.InsufficientPrivilege as exc:
            raise SystemExit(
                f"Cannot create 'svix' database: user '{settings.db_user}' lacks "
                "the CREATEDB privilege. Either pre-create it once with a "
                "privileged user:\n"
                f'    CREATE DATABASE svix OWNER "{settings.db_user}";\n'
                "or grant the privilege:\n"
                f'    ALTER ROLE "{settings.db_user}" CREATEDB;'
            ) from exc


if __name__ == "__main__":
    create_svix_db()
