import os
import sqlite3
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify


health_bp = Blueprint('health', __name__)


@health_bp.get('/healthz')
def healthz():
    """Lightweight health probe used by containers and uptime monitors."""
    db_ok = True
    database = current_app.config.get('DATABASE') or os.environ.get('DATABASE', 'clinic.db')

    try:
        conn = sqlite3.connect(database)
        conn.execute('SELECT 1')
        conn.close()
    except Exception:
        db_ok = False

    payload = {
        'status': 'ok' if db_ok else 'degraded',
        'database': 'ok' if db_ok else 'error',
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
    return jsonify(payload), (200 if db_ok else 503)
