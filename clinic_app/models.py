import sqlite3
from flask import g, current_app

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        database = current_app.config.get('DATABASE', 'clinic.db')
        db = g._database = sqlite3.connect(database)
        db.row_factory = sqlite3.Row
    return db

def get_all_meeting_notes():
    db = get_db()
    cursor = db.execute("SELECT * FROM meeting_notes")
    return cursor.fetchall()

def get_all_patient_bookings():
    db = get_db()
    cursor = db.execute("SELECT * FROM bookings")
    return cursor.fetchall()