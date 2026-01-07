import sqlite3
import os
from app.config import Config

# Get database path from Config
# Config.SQLALCHEMY_DATABASE_URI is likely something like "sqlite:///./app.db"
db_uri = Config.SQLALCHEMY_DATABASE_URI
if db_uri.startswith("sqlite:///"):
    db_path = db_uri.replace("sqlite:///", "")
else:
    print(f"Unsupported database URI: {db_uri}")
    exit(1)

# Handle relative paths (./app.db)
if db_path.startswith("./"):
    db_path = db_path[2:]
    
# Assuming the script is run from the project root
if not os.path.exists(db_path):
    # Try looking in instance folder if it's a flask app default
    instance_path = os.path.join("instance", db_path)
    if os.path.exists(instance_path):
        db_path = instance_path
    else:
        # Try absolute path from config if possible, or just print error
        print(f"Database file not found at: {db_path}")
        # Continue anyway, maybe it's an absolute path
        
print(f"Connecting to database: {db_path}")

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check if column exists
    cursor.execute("PRAGMA table_info(settings)")
    columns = [info[1] for info in cursor.fetchall()]
    
    if "full_page_submission" in columns:
        print("Column 'full_page_submission' already exists in 'settings' table.")
    else:
        print("Adding 'full_page_submission' column to 'settings' table...")
        # Add column with default value 0 (False)
        cursor.execute("ALTER TABLE settings ADD COLUMN full_page_submission BOOLEAN DEFAULT 0 NOT NULL")
        conn.commit()
        print("Migration successful!")
        
    conn.close()
    
except Exception as e:
    print(f"Error during migration: {str(e)}")
    exit(1)
