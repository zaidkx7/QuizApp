from flask import Flask, render_template, request, redirect, url_for, session, flash
from sqlalchemy.orm import Session
from functools import wraps
import json
import os
import re
from datetime import datetime
from typing import Optional
from rapidfuzz import fuzz

from database import engine, SessionLocal, Base
from models import User, Result, Quiz

# Create database tables
Base.metadata.create_all(bind=engine)

# Initialize Flask app
app = Flask(__name__)

# Configure session
# IMPORTANT: Change this secret key before deploying to production!
# Generate with: python3 -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY = "689eaa035980f7a2f09caaef195600c3b8f589a1a36cc696dae3425fefe587d5"
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SESSION_TYPE'] = 'filesystem'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Admin credentials
ADMIN_USERNAME = "zaid.sh"
ADMIN_PASSWORD = "admin@zaid.sh"


# Database session decorator
def with_db(f):
    """Decorator to provide database session to route handlers"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        db = SessionLocal()
        try:
            return f(db, *args, **kwargs)
        finally:
            db.close()
    return decorated_function


# Helper functions
def get_current_user(db: Session):
    """Get current user from session"""
    user_id = session.get("user_id")
    if user_id:
        return db.query(User).filter(User.id == user_id).first()
    return None


def normalize(text: str) -> str:
    """Normalize text for fuzzy matching"""
    if not text:
        return ""

    # Convert to lowercase
    text = text.lower()
    # Remove HTML brackets
    text = re.sub(r'[<>]', '', text)
    # Remove hyphens, underscores, and special characters
    text = re.sub(r'[-_.,;:!?(){}[\]"/\\]', ' ', text)
    # Collapse multiple spaces into one
    text = re.sub(r'\s+', ' ', text)
    # Trim leading/trailing spaces
    text = text.strip()
    return text


def is_fuzzy_correct(user_answer: str, correct_answer: str, threshold: int = 85) -> bool:
    """Check if user answer is correct using fuzzy string matching"""
    score = fuzz.ratio(normalize(user_answer), normalize(correct_answer))
    return score >= threshold


def load_quiz_by_id(quiz_id: int, db: Session):
    """Load quiz data from database and JSON file"""
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        return None, None

    quiz_path = f"questions/{quiz.filename}"
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

    # Calculate score out of 100
    score = (correct_answers / total_questions * 100) if total_questions > 0 else 0

    return score, results


# Routes
@app.route("/")
def index():
    """Landing page"""
    return render_template("index.html")


@app.route("/admin/login", methods=["GET", "POST"])
@with_db
def admin_login(db):
    """Admin login page and handler"""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            # Check if admin user exists in DB, if not create it
            admin_user = db.query(User).filter(User.username == ADMIN_USERNAME, User.role == "admin").first()
            if not admin_user:
                admin_user = User(username=ADMIN_USERNAME, role="admin")
                db.add(admin_user)
                db.commit()
                db.refresh(admin_user)

            # Set session
            session["user_id"] = admin_user.id
            session["role"] = "admin"
            return redirect(url_for("admin_dashboard"))

        return render_template("admin_login.html", error="Invalid credentials")

    return render_template("admin_login.html", error=None)


@app.route("/admin/dashboard")
@with_db
def admin_dashboard(db):
    """Admin dashboard"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin_login"))

    message = session.pop("message", None)
    return render_template("admin_dashboard.html", message=message)


@app.route("/admin/quizzes")
@with_db
def admin_quizzes(db):
    """Manage quizzes page"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin_login"))

    # Get all quizzes
    quizzes = db.query(Quiz).order_by(Quiz.created_at.desc()).all()

    message = session.pop("message", None)
    return render_template("admin_quizzes.html", quizzes=quizzes, message=message)


@app.route("/admin/quiz/upload", methods=["POST"])
@with_db
def upload_quiz(db):
    """Handle quiz file upload"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin_login"))

    try:
        file = request.files.get('file')

        if not file or not file.filename:
            session["message"] = "No file selected"
            return redirect(url_for("admin_quizzes"))

        # Read and parse JSON
        content = file.read()
        quiz_data = json.loads(content)

        # Validate JSON structure
        required_keys = ["title"]
        if not all(key in quiz_data for key in required_keys):
            session["message"] = "Invalid quiz format - must have 'title' field"
            return redirect(url_for("admin_quizzes"))

        # Generate unique filename
        import time
        filename = f"quiz_{int(time.time())}_{file.filename}"

        # Save to questions folder
        os.makedirs("questions", exist_ok=True)
        quiz_path = f"questions/{filename}"
        with open(quiz_path, "w", encoding="utf-8") as f:
            json.dump(quiz_data, f, indent=2)

        # Create Quiz record in database
        new_quiz = Quiz(
            title=quiz_data["title"],
            filename=filename
        )
        db.add(new_quiz)
        db.commit()

        session["message"] = f"Quiz '{quiz_data['title']}' uploaded successfully!"
        return redirect(url_for("admin_quizzes"))

    except json.JSONDecodeError:
        session["message"] = "Invalid JSON file"
        return redirect(url_for("admin_quizzes"))
    except Exception as e:
        session["message"] = f"Error uploading quiz: {str(e)}"
        return redirect(url_for("admin_quizzes"))


@app.route("/admin/quiz/delete/<int:quiz_id>", methods=["POST"])
@with_db
def delete_quiz(db, quiz_id):
    """Delete a quiz and its submissions"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin_login"))

    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if quiz:
        # Delete quiz file
        quiz_path = f"questions/{quiz.filename}"
        if os.path.exists(quiz_path):
            os.remove(quiz_path)

        # Delete all results for this quiz
        db.query(Result).filter(Result.quiz_id == quiz_id).delete()

        # Delete quiz from database
        db.delete(quiz)
        db.commit()

        session["message"] = f"Quiz '{quiz.title}' deleted successfully!"
    else:
        session["message"] = "Quiz not found"

    return redirect(url_for("admin_quizzes"))


@app.route("/admin/scores")
@with_db
def view_scores(db):
    """View all user scores"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin_login"))

    # Get all results with user info
    results = db.query(Result).join(User).order_by(Result.submitted_at.desc()).all()

    return render_template("scores.html", results=results)


@app.route("/user/register", methods=["GET", "POST"])
@with_db
def user_register(db):
    """User registration/login page and handler"""
    if request.method == "POST":
        user_id = request.form.get("user_id", "").strip()
        password = request.form.get("password", "").strip()

        if not user_id or len(user_id) == 0:
            return render_template("user_register.html", error="Student ID is required")

        if not password or len(password) == 0:
            return render_template("user_register.html", error="Password is required")

        # Check if user exists (only admin-created users can login)
        user = db.query(User).filter(User.user_id == user_id, User.role == "user").first()

        if not user:
            # User doesn't exist - show error
            return render_template("user_register.html", error="Invalid credentials. Please contact your administrator.")

        # Verify password
        if user.password != password:
            return render_template("user_register.html", error="Invalid credentials. Please contact your administrator.")

        # Set session
        session["user_id"] = user.id
        session["role"] = "user"

        return redirect(url_for("user_history"))

    return render_template("user_register.html", error=None)


@app.route("/user/history")
@with_db
def user_history(db):
    """Display user's quiz history"""
    try:
        # Check if user is logged in
        if session.get("role") != "user":
            return redirect(url_for("user_register"))

        # Get current user
        user = get_current_user(db)
        if not user:
            return redirect(url_for("user_register"))

        # Get all quizzes with user's submissions
        quizzes = db.query(Quiz).order_by(Quiz.created_at.desc()).all()

        # For each quiz, attach user's submission if exists
        for quiz in quizzes:
            quiz.user_submissions = [r for r in quiz.results if r.user_id == user.id]

        # Get all user's results
        results = db.query(Result).filter(Result.user_id == user.id).order_by(Result.submitted_at.desc()).all()

        username = user.user_id if user.user_id else user.username
        return render_template("user_history.html", username=username, quizzes=quizzes, results=results)
    except Exception as e:
        print(f"ERROR in user_history: {str(e)}")
        import traceback
        traceback.print_exc()
        return f"<h1>Error loading history</h1><p>{str(e)}</p>", 500


@app.route("/user/quiz/<int:quiz_id>")
@with_db
def take_quiz(db, quiz_id):
    """Display quiz for user"""
    try:
        # Check if user is logged in
        if session.get("role") != "user":
            return redirect(url_for("user_register"))

        # Get current user
        user = get_current_user(db)
        if not user:
            return redirect(url_for("user_register"))

        # Check if user already submitted this quiz
        existing_submission = db.query(Result).filter(
            Result.user_id == user.id,
            Result.quiz_id == quiz_id
        ).first()

        if existing_submission:
            session["message"] = "You have already submitted this quiz!"
            return redirect(url_for("view_result", result_id=existing_submission.id))

        # Load quiz
        quiz, quiz_data = load_quiz_by_id(quiz_id, db)
        if not quiz or not quiz_data:
            return "<h1>Quiz not found or unavailable.</h1>", 404

        return render_template("quiz.html", exam=quiz_data, quiz_id=quiz_id)
    except Exception as e:
        print(f"ERROR in take_quiz: {str(e)}")
        import traceback
        traceback.print_exc()
        return f"<h1>Error loading quiz</h1><p>{str(e)}</p>", 500


@app.route("/user/submit/<int:quiz_id>", methods=["POST"])
@with_db
def submit_quiz(db, quiz_id):
    """Handle quiz submission"""
    # Check if user is logged in
    if session.get("role") != "user":
        return redirect(url_for("user_register"))

    # Get current user
    user = get_current_user(db)
    if not user:
        return redirect(url_for("user_register"))

    # Check if user already submitted this quiz
    existing_submission = db.query(Result).filter(
        Result.user_id == user.id,
        Result.quiz_id == quiz_id
    ).first()

    if existing_submission:
        return redirect(url_for("view_result", result_id=existing_submission.id))

    # Load quiz
    quiz, quiz_data = load_quiz_by_id(quiz_id, db)
    if not quiz or not quiz_data:
        return "<h1>Quiz not found.</h1>", 404

    # Get form data
    form_data = request.form
    user_answers = dict(form_data)

    # Calculate score
    score, results = calculate_score(quiz_data, user_answers)

    # Save result to database
    result = Result(
        user_id=user.id,
        quiz_id=quiz_id,
        score=score,
        answers=json.dumps(results)
    )
    db.add(result)
    db.commit()
    db.refresh(result)

    return redirect(url_for("view_result", result_id=result.id))


@app.route("/user/result/<int:result_id>")
@with_db
def view_result(db, result_id):
    """Display user's result by ID"""
    # Check if user is logged in
    if session.get("role") != "user":
        return redirect(url_for("user_register"))

    # Get current user
    user = get_current_user(db)
    if not user:
        return redirect(url_for("user_register"))

    # Get result from database
    result = db.query(Result).filter(Result.id == result_id, Result.user_id == user.id).first()
    if not result:
        return redirect(url_for("user_history"))

    # Parse results from JSON
    results = json.loads(result.answers)

    # Get quiz title from relationship
    exam_title = result.quiz.title if result.quiz else "Exam"

    return render_template("result.html", score=result.score, results=results, exam_title=exam_title)


@app.route("/admin/quiz/preview/<int:quiz_id>")
@with_db
def admin_quiz_preview(db, quiz_id):
    """Preview a quiz with correct answers"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin_login"))

    # Load quiz
    quiz, quiz_data = load_quiz_by_id(quiz_id, db)
    if not quiz or not quiz_data:
        return "<h1>Quiz not found.</h1>", 404

    return render_template("admin_quiz_preview.html", exam=quiz_data)

@app.route("/admin/quizzes/delete-all", methods=["POST"])
@with_db
def admin_delete_all_quizzes(db):
    """Delete all quizzes"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin_login"))

    # Delete all quizzes
    db.query(Quiz).delete()
    db.commit()

    session["message"] = "All quizzes deleted successfully!"
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/submission/<int:result_id>")
@with_db
def admin_view_submission(db, result_id):
    """View a specific user's submission"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin_login"))

    # Get result from database
    result = db.query(Result).filter(Result.id == result_id).first()
    if not result:
        return redirect(url_for("view_scores"))

    # Parse results from JSON
    results = json.loads(result.answers)

    # Get quiz title from relationship
    exam_title = result.quiz.title if result.quiz else "Exam"

    submitted_at = result.submitted_at.strftime('%B %d, %Y at %I:%M %p')
    return render_template("admin_user_submission.html",
                         username=result.user.username,
                         score=result.score,
                         results=results,
                         exam_title=exam_title,
                         submitted_at=submitted_at)


@app.route("/admin/submissions/delete-all", methods=["POST"])
@with_db
def admin_delete_all_submissions(db):
    """Delete all student submissions"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin_login"))

    # Delete all results
    db.query(Result).delete()
    db.commit()

    session["message"] = "All submissions deleted successfully!"
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/users")
@with_db
def admin_users(db):
    """Manage users page"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin_login"))

    # Get all users (excluding admin)
    users = db.query(User).filter(User.role == "user").order_by(User.user_id).all()

    message = session.pop("message", None)
    return render_template("admin_users.html", users=users, message=message)


@app.route("/admin/users/add", methods=["POST"])
@with_db
def admin_add_user(db):
    """Add a new user"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin_login"))

    user_id = request.form.get("user_id")
    password = request.form.get("password")

    # Check if user already exists
    existing_user = db.query(User).filter(User.user_id == user_id).first()
    if existing_user:
        session["message"] = f"User with ID {user_id} already exists!"
        return redirect(url_for("admin_users"))

    # Create new user
    new_user = User(
        username=f"Student_{user_id}",
        user_id=user_id,
        password=password,
        role="user"
    )
    db.add(new_user)
    db.commit()

    session["message"] = f"User {user_id} added successfully!"
    return redirect(url_for("admin_users"))


@app.route("/admin/users/edit", methods=["POST"])
@with_db
def admin_edit_user(db):
    """Edit a user"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin_login"))

    user_db_id = request.form.get("user_db_id", type=int)
    user_id = request.form.get("user_id")
    password = request.form.get("password")

    # Get user
    user = db.query(User).filter(User.id == user_db_id).first()
    if not user:
        session["message"] = "User not found!"
        return redirect(url_for("admin_users"))

    # Check if new user_id conflicts with another user
    existing_user = db.query(User).filter(User.user_id == user_id, User.id != user_db_id).first()
    if existing_user:
        session["message"] = f"User ID {user_id} is already taken!"
        return redirect(url_for("admin_users"))

    # Update user
    user.user_id = user_id
    user.password = password
    user.username = f"Student_{user_id}"
    db.commit()

    session["message"] = f"User {user_id} updated successfully!"
    return redirect(url_for("admin_users"))


@app.route("/admin/users/delete/<int:user_db_id>", methods=["POST"])
@with_db
def admin_delete_user(db, user_db_id):
    """Delete a user and their submissions"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin_login"))

    # Get user
    user = db.query(User).filter(User.id == user_db_id).first()
    if not user:
        session["message"] = "User not found!"
        return redirect(url_for("admin_users"))

    # Delete user's results first
    db.query(Result).filter(Result.user_id == user_db_id).delete()

    # Delete user
    db.delete(user)
    db.commit()

    session["message"] = "User deleted successfully!"
    return redirect(url_for("admin_users"))


@app.route("/logout")
def logout():
    """Logout user"""
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
