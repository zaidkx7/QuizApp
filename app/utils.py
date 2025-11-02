import os
import re
import json

from flask import session
from rapidfuzz import fuzz
from sqlalchemy.orm import Session
from app.models import User, Quiz, Settings

# User helpers
def get_current_user(db: Session):
    """Get current user from session"""
    user_id = session.get("user_id")
    if user_id:
        return db.query(User).filter(User.id == user_id).first()
    return None


# Settings helpers
def get_or_create_settings(db: Session):
    """Get settings from database or create default if not exists"""
    settings = db.query(Settings).first()
    if not settings:
        settings = Settings(max_attempts=3, smtp_enabled=True)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def get_max_attempts(db: Session):
    """Get the maximum number of quiz attempts from settings"""
    settings = get_or_create_settings(db)
    return settings.max_attempts


def is_smtp_enabled(db: Session):
    """Check if SMTP email sending is enabled"""
    settings = get_or_create_settings(db)
    return settings.smtp_enabled


# Text processing helpers
def normalize(text: str) -> str:
    """Normalize text for fuzzy matching"""
    if not text:
        return ""
    
    # Convert to lowercase
    text = text.lower()
    # Remove HTML brackets
    text = re.sub(r'[<>]', '', text)
    # Remove hyphens, underscores, and special characters
    text = re.sub(r'[-_.,;:!?(){}\[\]"/\\]', ' ', text)
    # Collapse multiple spaces into one
    text = re.sub(r'\s+', ' ', text)
    # Trim leading/trailing spaces
    text = text.strip()
    return text


def is_fuzzy_correct(user_answer: str, correct_answer: str, threshold: int = 85) -> bool:
    """Check if user answer is correct using fuzzy string matching"""
    score = fuzz.ratio(normalize(user_answer), normalize(correct_answer))
    return score >= threshold


# Quiz helpers
def load_quiz_by_id(quiz_id: int, db: Session):
    """Load quiz data from database and JSON file"""
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        return None, None
    
    # Updated path to new location
    basedir = os.path.abspath(os.path.dirname(__file__))
    quiz_path = os.path.join(basedir, 'data', 'questions', quiz.filename)
    
    if os.path.exists(quiz_path):
        with open(quiz_path, "r", encoding="utf-8") as f:
            quiz_data = json.load(f)
            return quiz, quiz_data
    return quiz, None


def calculate_score(exam_data, user_answers):
    """Calculate score and prepare results"""
    total_questions = 0
    correct_answers = 0
    results = {
        "fill_in_the_blanks": [],
        "true_false": [],
        "mcqs": []
    }
    
    # Process fill in the blanks
    if "fill_in_the_blanks" in exam_data:
        for idx, question in enumerate(exam_data["fill_in_the_blanks"]):
            total_questions += 1
            user_answer = user_answers.get(f"fib_{idx}", "").strip()
            correct_answer = question["answer"].strip()
            # Use fuzzy matching for flexible answer checking
            is_correct = is_fuzzy_correct(user_answer, correct_answer)
            if is_correct:
                correct_answers += 1
            results["fill_in_the_blanks"].append({
                "question": question["question"],
                "user_answer": user_answer,
                "correct_answer": correct_answer,
                "is_correct": is_correct
            })
    
    # Process true/false
    if "true_false" in exam_data:
        for idx, question in enumerate(exam_data["true_false"]):
            total_questions += 1
            user_answer = user_answers.get(f"tf_{idx}")
            if user_answer is not None:
                user_answer = user_answer.lower() == "true"
            correct_answer = question["answer"]
            is_correct = user_answer == correct_answer
            if is_correct:
                correct_answers += 1
            results["true_false"].append({
                "question": question["question"],
                "user_answer": user_answer,
                "correct_answer": correct_answer,
                "is_correct": is_correct
            })
    
    # Process MCQs
    if "mcqs" in exam_data:
        for idx, question in enumerate(exam_data["mcqs"]):
            total_questions += 1
            user_answer = user_answers.get(f"mcq_{idx}", "")
            correct_answer = question["answer"]
            is_correct = user_answer == correct_answer
            if is_correct:
                correct_answers += 1
            results["mcqs"].append({
                "question": question["question"],
                "options": question["options"],
                "user_answer": user_answer,
                "correct_answer": correct_answer,
                "is_correct": is_correct
            })
    
    # Calculate percentage
    if total_questions > 0:
        percentage = (correct_answers / total_questions) * 100
    else:
        percentage = 0
    
    return percentage, results
