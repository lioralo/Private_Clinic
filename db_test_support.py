"""Shared test helper: build the full production schema for a fresh test DB.

Historically the unit tests built their schema from ``clinic_app/schema.sql`` +
``_run_db_migrations()``, which is only a SUBSET of the real, Alembic-managed
production schema. Tables/columns added later solely via Alembic (``assessments``,
``treatment_plans``, the ``notifications.category`` column, ...) were therefore
missing, so a large batch of tests failed with ``no such table`` / ``no such
column`` even though the application code was correct.

This helper builds the schema exactly like production does (``alembic upgrade
heads``), so tests exercise the same schema the app actually runs against.
Callers typically follow it with the idempotent ``_run_db_migrations`` as a
belt-and-suspenders superset guard.

The Alembic build is performed once per test session and cached as a template
file that is copied for each test — copying a small SQLite file is far cheaper
than re-running every migration hundreds of times.
"""

import os
import shutil
import tempfile

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_TEMPLATE_DB_PATH = None


def _build_template_db():
    from alembic import command
    from alembic.config import Config

    fd, template_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    # Remove the empty placeholder so Alembic/SQLite create a clean database.
    os.unlink(template_path)

    cfg = Config(os.path.join(_REPO_ROOT, 'alembic.ini'))
    cfg.set_main_option('sqlalchemy.url', f'sqlite:///{template_path}')
    command.upgrade(cfg, 'heads')
    return template_path


def build_test_schema(database_path):
    """Populate ``database_path`` with the full Alembic-head production schema."""
    global _TEMPLATE_DB_PATH
    if not _TEMPLATE_DB_PATH or not os.path.exists(_TEMPLATE_DB_PATH):
        _TEMPLATE_DB_PATH = _build_template_db()
    shutil.copyfile(_TEMPLATE_DB_PATH, database_path)
