import sqlite3
import shutil
import os
import datetime
import argparse

DB_FILE = "clinic.db"
BACKUP_DIR = "backups"

def backup_database():
    if not os.path.exists(DB_FILE):
        print(f"Error: Database file '{DB_FILE}' not found.")
        return

    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"clinic_backup_{timestamp}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)

    try:
        # Use sqlite3 to backup safely even if in use (though simple copy works for small sqlite usually)
        # Using shutil.copy2 for simple file copy. 
        # For a live DB, sqlite3 API backup is better, but this script is simple.
        # Let's try sqlite3 online backup API if possible, or just copy.
        
        # Using connection to backup
        src = sqlite3.connect(DB_FILE)
        dst = sqlite3.connect(backup_path)
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
        
        print(f"Backup successful: {backup_path}")
    except Exception as e:
        print(f"Backup failed: {e}")

if __name__ == "__main__":
    backup_database()
