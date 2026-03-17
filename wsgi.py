from app import app, ensure_runtime_paths, init_db

# Prepare storage paths and schema when the web server boots.
ensure_runtime_paths()
with app.app_context():
    init_db()
