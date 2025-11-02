#!/usr/bin/env python
"""
Database Initialization Script
Run this script to create/recreate all database tables.

Usage:
    python init_db.py
"""

from app import create_app
from app.database import Base, engine
from app.models import User, Quiz, Result, Settings

def init_database():
    """Initialize the database by creating all tables"""
    print("Initializing database...")

    # Create all tables
    Base.metadata.create_all(bind=engine)

    print("✅ Database tables created successfully!")
    print("\nCreated tables:")
    print("  - users")
    print("  - quizzes")
    print("  - results")
    print("  - settings")
    print("\nDatabase location: instance/quiz_app.db")

if __name__ == "__main__":
    init_database()
