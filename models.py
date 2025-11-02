from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=True)  # Student ID for students
    password = Column(String, nullable=True)  # Password for students
    email = Column(String, nullable=True)  # Email for sending results
    role = Column(String, nullable=False)  # "admin" or "user"

    # Relationship to results
    results = relationship("Result", back_populates="user")

class Quiz(Base):
    __tablename__ = "quizzes"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    filename = Column(String, unique=True, nullable=False)  # Stored in questions/ folder
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship to results
    results = relationship("Result", back_populates="quiz")

class Result(Base):
    __tablename__ = "results"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    quiz_id = Column(Integer, ForeignKey("quizzes.id"), nullable=False)
    score = Column(Float, nullable=False)
    submitted_at = Column(DateTime, default=datetime.utcnow)
    answers = Column(Text, nullable=False)  # Store as JSON string

    # Relationships
    user = relationship("User", back_populates="results")
    quiz = relationship("Quiz", back_populates="results")

class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    max_attempts = Column(Integer, default=3, nullable=False)  # Maximum quiz attempts per user
    smtp_enabled = Column(Boolean, default=True, nullable=False)  # Enable/disable email sending
