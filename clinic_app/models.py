from flask import g

def get_db():
    from app import get_db as _app_get_db
    return _app_get_db()

def get_all_meeting_notes():
    db = get_db()
    cursor = db.execute("SELECT * FROM meeting_notes")
    return cursor.fetchall()

def get_all_patient_bookings():
    db = get_db()
    cursor = db.execute("SELECT * FROM bookings")
    return cursor.fetchall()
