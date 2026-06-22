import sqlite3
from flask import g, current_app


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        database = current_app.config.get('DATABASE', 'clinic.db')
        db = g._database = sqlite3.connect(database)
        db.row_factory = sqlite3.Row
    return db
