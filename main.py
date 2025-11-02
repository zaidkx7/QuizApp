import json
import os
import re

from flask import Flask, render_template, request, redirect, url_for, session, flash
from sqlalchemy.orm import Session
from functools import wraps
from datetime import datetime
from rapidfuzz import fuzz

from database import engine, SessionLocal, Base
from models import User, Result, Quiz, Settings
from mail import SMTPMailer

# Create database tables
Base.metadata.create_all(bind=engine)

# Initialize Flask app
app = Flask(__name__)

# Configure session
# IMPORTANT: Change this secret key before deploying to production!
# Generate with: python3 -c "import secrets; print(secrets.token_hex(32))"
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")
app.config['SESSION_TYPE'] = 'filesystem'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Admin credentials
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")


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

    # Get all users (excluding admin)
    users = db.query(User).filter(User.role == "user").order_by(User.user_id).all()

    # For each user, group their submissions by quiz
    for user in users:
        user_results = db.query(Result).filter(Result.user_id == user.id).order_by(Result.quiz_id, Result.submitted_at).all()

        # Group results by quiz
        quiz_groups = {}
        for result in user_results:
            quiz_id = result.quiz_id
            if quiz_id not in quiz_groups:
                quiz_groups[quiz_id] = {
                    'quiz': result.quiz,
                    'attempts': []
                }
            quiz_groups[quiz_id]['attempts'].append(result)

        # Add attempt numbers to each result
        for quiz_id, group in quiz_groups.items():
            for idx, result in enumerate(group['attempts'], start=1):
                result.attempt_number = idx

        user.quiz_groups = quiz_groups

    return render_template("scores.html", users=users)


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

        # For each quiz, attach user's submissions with attempt numbers
        for quiz in quizzes:
            user_submissions = [r for r in quiz.results if r.user_id == user.id]
            # Sort by submission date
            user_submissions.sort(key=lambda x: x.submitted_at)
            # Add attempt numbers
            for idx, submission in enumerate(user_submissions, start=1):
                submission.attempt_number = idx
            quiz.user_submissions = user_submissions

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

        # Calculate attempt number for this quiz
        attempt_count = db.query(Result).filter(
            Result.user_id == user.id,
            Result.quiz_id == quiz_id
        ).count()

        # Check if user has reached maximum attempts
        max_attempts = get_max_attempts(db)
        if attempt_count >= max_attempts:
            session["message"] = f"You have reached the maximum number of attempts ({max_attempts}) for this quiz!"
            # Redirect to their most recent result
            latest_result = db.query(Result).filter(
                Result.user_id == user.id,
                Result.quiz_id == quiz_id
            ).order_by(Result.submitted_at.desc()).first()
            return redirect(url_for("view_result", result_id=latest_result.id))

        attempt_number = attempt_count + 1

        # Load quiz
        quiz, quiz_data = load_quiz_by_id(quiz_id, db)
        if not quiz or not quiz_data:
            return "<h1>Quiz not found or unavailable.</h1>", 404

        return render_template("quiz.html", exam=quiz_data, quiz_id=quiz_id, attempt_number=attempt_number)
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

    # Check if user has reached maximum attempts
    attempt_count = db.query(Result).filter(
        Result.user_id == user.id,
        Result.quiz_id == quiz_id
    ).count()

    max_attempts = get_max_attempts(db)
    if attempt_count >= max_attempts:
        session["message"] = f"You have reached the maximum number of attempts ({max_attempts}) for this quiz!"
        latest_result = db.query(Result).filter(
            Result.user_id == user.id,
            Result.quiz_id == quiz_id
        ).order_by(Result.submitted_at.desc()).first()
        return redirect(url_for("view_result", result_id=latest_result.id))

    # Load quiz
    quiz, quiz_data = load_quiz_by_id(quiz_id, db)
    if not quiz or not quiz_data:
        return "<h1>Quiz not found.</h1>", 404

    # Get form data
    form_data = request.form
    user_answers = dict(form_data)

    # Calculate score
    score, results = calculate_score(quiz_data, user_answers)

    # Calculate attempt number
    attempt_number = attempt_count + 1

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

    # Send result email if user has email
    if user.email:
        user_name = user.user_id if user.user_id else user.username

        # Calculate total questions and correct count
        total_questions = (
            len(results.get('fill_in_the_blanks', [])) +
            len(results.get('true_false', [])) +
            len(results.get('mcqs', []))
        )

        correct_count = sum(
            1 for section in results.values()
            for item in section
            if item.get('is_correct')
        )

        # Prepare email context
        email_context = {
            'user_name': user_name,
            'quiz_title': quiz.title,
            'score': score,
            'attempt_number': attempt_number,
            'timestamp': datetime.now().strftime('%B %d, %Y at %I:%M %p'),
            'passed': score >= 70,
            'results': results,
            'result_id': result.id,
            'total_questions': total_questions,
            'correct_count': correct_count
        }

        # Send email using SMTPMailer with templates (if SMTP is enabled)
        if is_smtp_enabled(db):
            try:
                mailer = SMTPMailer()
                mailer.send_template(
                    to_email=user.email,
                    subject=f"Quiz Result: {quiz.title}",
                    template_name='quiz_result',
                    context=email_context
                )
            except Exception as e:
                print(f"Failed to send email: {str(e)}")
        else:
            print(f"SMTP is disabled. Email not sent to {user.email}")

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

    # Calculate attempt number for this result
    all_attempts = db.query(Result).filter(
        Result.user_id == user.id,
        Result.quiz_id == result.quiz_id
    ).order_by(Result.submitted_at).all()

    attempt_number = None
    for idx, attempt in enumerate(all_attempts, start=1):
        if attempt.id == result.id:
            attempt_number = idx
            break

    # Check if user can retake (less than max attempts)
    max_attempts = get_max_attempts(db)
    can_retake = len(all_attempts) < max_attempts

    # Parse results from JSON
    results = json.loads(result.answers)

    # Get quiz title and ID from relationship
    exam_title = result.quiz.title if result.quiz else "Exam"
    quiz_id = result.quiz_id

    # Get the message from session if any
    message = session.pop("message", None)

    return render_template("result.html", score=result.score, results=results, exam_title=exam_title,
                         attempt_number=attempt_number, quiz_id=quiz_id, can_retake=can_retake, message=message)


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
    email = request.form.get("email")

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
        email=email,
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
    email = request.form.get("email")

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
    user.email = email
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


@app.route("/admin/settings", methods=["GET"])
@with_db
def admin_settings(db):
    """Admin settings page"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin_login"))

    # Get current settings
    settings = get_or_create_settings(db)

    # Check SMTP configuration
    smtp_configured = all([
        os.getenv("EMAIL_USERNAME"),
        os.getenv("EMAIL_PASSWORD"),
        os.getenv("EMAIL_HOST"),
        os.getenv("EMAIL_FROM")
    ])

    # Get message from session if available
    message = session.pop("message", None)

    return render_template(
        "admin_settings.html",
        settings=settings,
        smtp_configured=smtp_configured,
        message=message
    )


@app.route("/admin/settings/update", methods=["POST"])
@with_db
def admin_settings_update(db):
    """Update admin settings"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin_login"))

    # Get form data
    max_attempts = request.form.get("max_attempts", type=int)
    smtp_enabled = request.form.get("smtp_enabled") == "on"

    # Validate max_attempts
    if not max_attempts or max_attempts < 1 or max_attempts > 999:
        session["message"] = "Error: Maximum attempts must be between 1 and 999!"
        return redirect(url_for("admin_settings"))

    # Check SMTP configuration if enabling SMTP
    if smtp_enabled:
        smtp_configured = all([
            os.getenv("EMAIL_USERNAME"),
            os.getenv("EMAIL_PASSWORD"),
            os.getenv("EMAIL_HOST"),
            os.getenv("EMAIL_FROM")
        ])
        if not smtp_configured:
            session["message"] = "Warning: SMTP enabled but credentials are not fully configured in .env file!"

    # Update settings
    settings = get_or_create_settings(db)
    settings.max_attempts = max_attempts
    settings.smtp_enabled = smtp_enabled
    db.commit()

    session["message"] = "Settings updated successfully!"
    return redirect(url_for("admin_settings"))


@app.route("/logout")
def logout():
    """Logout user"""
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
