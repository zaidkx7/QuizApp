import sqlite3
import os

DB_PATH = os.path.join("instance", "quiz_app.db")

def migrate_db():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Add columns if they don't exist
        columns = [
            ("first_name", "VARCHAR"),
            ("last_name", "VARCHAR"),
            ("profile_pic", "VARCHAR")
        ]

        for col_name, col_type in columns:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
                print(f"Added column {col_name}")
            except sqlite3.OperationalError as e:
                # Column might already exist
                if "duplicate column name" in str(e):
                    print(f"Column {col_name} already exists")
                else:
                    print(f"Error adding {col_name}: {e}")

        conn.commit()
        print("Migration completed successfully.")
    except Exception as e:
        print(f"Migration failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_db()
