"""Provenance of a build, stored in the ``Build_Info`` table and in
``PRAGMA user_version``.

The build date is taken from ``SOURCE_DATE_EPOCH`` when set, so that two
builds of the same inputs can produce identical databases.
"""

import datetime
import os
import platform
import sqlite3

import pandas as pd
import sqlalchemy

import edhiphy
from edhiphy.schema import SCHEMA_VERSION, Build_Info


def build_date() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        when = datetime.datetime.fromtimestamp(int(epoch), datetime.timezone.utc)
    else:
        when = datetime.datetime.now(datetime.timezone.utc)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_items(items) -> dict:
    """Parse ``key=value`` arguments."""
    info = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise SystemExit(f"--info expects key=value, got {item!r}")
        info[key] = value
    return info


def collect(items: dict) -> dict:
    info = {
        "schema_version": str(SCHEMA_VERSION),
        "edhiphy_version": edhiphy.__version__,
        "build_date": build_date(),
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "sqlite": sqlite3.sqlite_version,
    }
    info.update(items)
    return info


def write(conn: sqlalchemy.Connection, info: dict) -> None:
    conn.execute(Build_Info.delete().where(Build_Info.c.key.in_(list(info))))
    conn.execute(
        Build_Info.insert(), [{"key": k, "value": v} for k, v in sorted(info.items())]
    )
    conn.exec_driver_sql(f"PRAGMA user_version = {SCHEMA_VERSION}")
