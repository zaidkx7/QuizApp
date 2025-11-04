import os
import json

from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session

from app.config import Config
from app.database import SessionLocal
from app.models import User, Quiz, Result
from app.utils import get_or_create_settings, load_quiz_by_id, is_smtp_enabled, get_max_attempts

admin = Blueprint('admin', __name__, url_prefix='/admin')

def with_db(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        db = SessionLocal()
        try:
            return f(db, *args, **kwargs)
        finally:
            db.close()
    return decorated_function

# SEE NEXT COMMENT FOR ROUTES - File is too large for single creation
# Copy remaining routes from main.py admin sections
@admin.route("/login", methods=["GET", "POST"])
@with_db
def admin_login(db):
    """Admin login page and handler"""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == Config.ADMIN_USERNAME and password == Config.ADMIN_PASSWORD:
            # Check if admin user exists in DB, if not create it
            admin_user = db.query(User).filter(User.username == Config.ADMIN_USERNAME, User.role == "admin").first()
            if not admin_user:
                admin_user = User(username=Config.ADMIN_USERNAME, role="admin")
                db.add(admin_user)
                db.commit()
                db.refresh(admin_user)

            # Set session
            session["user_id"] = admin_user.id
            session["role"] = "admin"
            return redirect(url_for("admin.admin_dashboard"))

        return render_template("admin/login.html", error="Invalid credentials")

    return render_template("admin/login.html", error=None)


@admin.route("/dashboard")
@with_db
def admin_dashboard(db):
    """Admin dashboard"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin.admin_login"))

    message = session.pop("message", None)
    return render_template("admin/dashboard.html", message=message)


@admin.route("/quizzes")
@with_db
def admin_quizzes(db):
    """Manage quizzes page"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin.admin_login"))

    try:
        # Get all quizzes
        quizzes = db.query(Quiz).order_by(Quiz.created_at.desc()).all()
    except Exception as e:
        print(f"Database error: {str(e)}")
        quizzes = []
        session["message"] = "Database error. Please ensure the database is initialized."

    message = session.pop("message", None)
    return render_template("admin/quizzes.html", quizzes=quizzes, message=message)


@admin.route("/quiz/upload", methods=["POST"])
@with_db
def upload_quiz(db):
    """Handle quiz file upload"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin.admin_login"))

    try:
        file = request.files.get('file')

        if not file or not file.filename:
            session["message"] = "No file selected"
            return redirect(url_for("admin.admin_quizzes"))

        # Read and parse JSON
        content = file.read()
        quiz_data = json.loads(content)

        # Validate JSON structure
        required_keys = ["title"]
        if not all(key in quiz_data for key in required_keys):
            session["message"] = "Invalid quiz format - must have 'title' field"
            return redirect(url_for("admin.admin_quizzes"))

        # Generate unique filename
        import time
        filename = f"quiz_{int(time.time())}_{file.filename}"

        # Save to questions folder (app/data/questions)
        # Get app directory (parent of blueprints directory)
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        questions_dir = os.path.join(app_dir, "data", "questions")
        os.makedirs(questions_dir, exist_ok=True)
        quiz_path = os.path.join(questions_dir, filename)
        with open(quiz_path, "w", encoding="utf-8") as f:
            json.dump(quiz_data, f, indent=2)

        # Create Quiz record in database
        new_quiz = Quiz(
            title=quiz_data["title"],
            filename=filename
        )
        db.add(new_quiz)
        db.commit()
        db.refresh(new_quiz)  # Refresh to get the new quiz ID

        # Send email notification to all students about new quiz
        email_count = 0
        if is_smtp_enabled(db):
            from app.mail import SMTPMailer
            from app.config import Config

            # Get all students with email addresses
            students = db.query(User).filter(
                User.role == "user",
                User.email.isnot(None),
                User.email != ""
            ).all()

            if students:
                mailer = SMTPMailer()

                # Get max attempts setting
                max_attempts = get_max_attempts(db)

                # Prepare email context
                email_context = {
                    'quiz_title': quiz_data['title'],
                    'quiz_id': new_quiz.id,
                    'max_attempts': max_attempts,
                    'base_url': Config.BASE_URL
                }

                # Send email to each student
                for student in students:
                    try:
                        success = mailer.send_template(
                            to_email=student.email,
                            subject=f"New Quiz Available: {quiz_data['title']}",
                            template_name='student_quiz_reminder',
                            context=email_context
                        )
                        if success:
                            email_count += 1
                    except Exception as e:
                        print(f"Failed to send email to {student.email}: {str(e)}")

                session["message"] = f"Quiz '{quiz_data['title']}' uploaded successfully! Email notifications sent to {email_count} student(s)."
            else:
                session["message"] = f"Quiz '{quiz_data['title']}' uploaded successfully! (No students with email addresses)"
        else:
            session["message"] = f"Quiz '{quiz_data['title']}' uploaded successfully!"

        return redirect(url_for("admin.admin_quizzes"))

    except json.JSONDecodeError:
        session["message"] = "Invalid JSON file"
        return redirect(url_for("admin.admin_quizzes"))
    except Exception as e:
        session["message"] = f"Error uploading quiz: {str(e)}"
        return redirect(url_for("admin.admin_quizzes"))


@admin.route("/quiz/delete/<int:quiz_id>", methods=["POST"])
@with_db
def delete_quiz(db, quiz_id):
    """Delete a quiz and its submissions"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin.admin_login"))

    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if quiz:
        # Delete quiz file from app/data/questions
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        quiz_path = os.path.join(app_dir, "data", "questions", quiz.filename)
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

    return redirect(url_for("admin.admin_quizzes"))


@admin.route("/scores")
@with_db
def view_scores(db):
    """View all user scores"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin.admin_login"))

    try:
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

    except Exception as e:
        print(f"Database error: {str(e)}")
        users = []

    return render_template("admin/scores.html", users=users)

@admin.route("/quiz/preview/<int:quiz_id>")
@with_db
def admin_quiz_preview(db, quiz_id):
    """Preview a quiz with correct answers"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin.admin_login"))

    # Load quiz
    quiz, quiz_data = load_quiz_by_id(quiz_id, db)
    if not quiz or not quiz_data:
        return "<h1>Quiz not found.</h1>", 404

    return render_template("admin/quiz_preview.html", exam=quiz_data)

@admin.route("/quizzes/delete-all", methods=["POST"])
@with_db
def admin_delete_all_quizzes(db):
    """Delete all quizzes"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin.admin_login"))

    # Delete all quizzes
    db.query(Quiz).delete()
    db.commit()

    session["message"] = "All quizzes deleted successfully!"
    return redirect(url_for("admin.admin_dashboard"))


@admin.route("/submission/<int:result_id>")
@with_db
def admin_view_submission(db, result_id):
    """View a specific user's submission"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin.admin_login"))

    # Get result from database
    result = db.query(Result).filter(Result.id == result_id).first()
    if not result:
        return redirect(url_for("admin.view_scores"))

    # Parse results from JSON
    results = json.loads(result.answers)

    # Get quiz title from relationship
    exam_title = result.quiz.title if result.quiz else "Exam"

    submitted_at = result.submitted_at.strftime('%B %d, %Y at %I:%M %p')
    return render_template("admin/user_submission.html",
                         username=result.user.username,
                         score=result.score,
                         results=results,
                         exam_title=exam_title,
                         submitted_at=submitted_at)


@admin.route("/submissions/delete-all", methods=["POST"])
@with_db
def admin_delete_all_submissions(db):
    """Delete all student submissions"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin.admin_login"))

    # Delete all results
    db.query(Result).delete()
    db.commit()

    session["message"] = "All submissions deleted successfully!"
    return redirect(url_for("admin.admin_dashboard"))


@admin.route("/users")
@with_db
def admin_users(db):
    """Manage users page"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin.admin_login"))

    try:
        # Get all users (excluding admin)
        users = db.query(User).filter(User.role == "user").order_by(User.user_id).all()
    except Exception as e:
        print(f"Database error: {str(e)}")
        users = []
        session["message"] = "Database error. Please ensure the database is initialized."

    message = session.pop("message", None)
    return render_template("admin/users.html", users=users, message=message)


@admin.route("/users/add", methods=["POST"])
@with_db
def admin_add_user(db):
    """Add a new user"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin.admin_login"))

    user_id = request.form.get("user_id")
    password = request.form.get("password")
    email = request.form.get("email")

    # Check if user already exists
    existing_user = db.query(User).filter(User.user_id == user_id).first()
    if existing_user:
        session["message"] = f"User with ID {user_id} already exists!"
        return redirect(url_for("admin.admin_users"))

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
    return redirect(url_for("admin.admin_users"))


@admin.route("/users/edit", methods=["POST"])
@with_db
def admin_edit_user(db):
    """Edit a user"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin.admin_login"))

    user_db_id = request.form.get("user_db_id", type=int)
    user_id = request.form.get("user_id")
    password = request.form.get("password")
    email = request.form.get("email")

    # Get user
    user = db.query(User).filter(User.id == user_db_id).first()
    if not user:
        session["message"] = "User not found!"
        return redirect(url_for("admin.admin_users"))

    # Check if new user_id conflicts with another user
    existing_user = db.query(User).filter(User.user_id == user_id, User.id != user_db_id).first()
    if existing_user:
        session["message"] = f"User ID {user_id} is already taken!"
        return redirect(url_for("admin.admin_users"))

    # Update user
    user.user_id = user_id
    user.password = password
    user.email = email
    user.username = f"Student_{user_id}"
    db.commit()

    session["message"] = f"User {user_id} updated successfully!"
    return redirect(url_for("admin.admin_users"))


@admin.route("/users/delete/<int:user_db_id>", methods=["POST"])
@with_db
def admin_delete_user(db, user_db_id):
    """Delete a user and their submissions"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin.admin_login"))

    # Get user
    user = db.query(User).filter(User.id == user_db_id).first()
    if not user:
        session["message"] = "User not found!"
        return redirect(url_for("admin.admin_users"))

    # Delete user's results first
    db.query(Result).filter(Result.user_id == user_db_id).delete()

    # Delete user
    db.delete(user)
    db.commit()

    session["message"] = "User deleted successfully!"
    return redirect(url_for("admin.admin_users"))


@admin.route("/settings", methods=["GET"])
@with_db
def admin_settings(db):
    """Admin settings page"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin.admin_login"))

    # Get current settings
    settings = get_or_create_settings(db)

    # Check SMTP configuration
    smtp_configured = all([
        Config.EMAIL_USERNAME,
        Config.EMAIL_PASSWORD,
        Config.EMAIL_HOST,
        Config.EMAIL_FROM
    ])

    # Get message from session if available
    message = session.pop("message", None)

    return render_template(
        "admin/settings.html",
        settings=settings,
        smtp_configured=smtp_configured,
        message=message
    )


@admin.route("/settings/update", methods=["POST"])
@with_db
def admin_settings_update(db):
    """Update admin settings"""
    # Check if user is admin
    if session.get("role") != "admin":
        return redirect(url_for("admin.admin_login"))

    # Get form data
    max_attempts = request.form.get("max_attempts", type=int)
    smtp_enabled = request.form.get("smtp_enabled") == "on"

    # Validate max_attempts
    if not max_attempts or max_attempts < 1 or max_attempts > 999:
        session["message"] = "Error: Maximum attempts must be between 1 and 999!"
        return redirect(url_for("admin.admin_settings"))

    # Check SMTP configuration if enabling SMTP
    if smtp_enabled:
        smtp_configured = all([
            Config.EMAIL_USERNAME,
            Config.EMAIL_PASSWORD,
            Config.EMAIL_HOST,
            Config.EMAIL_FROM
        ])
        if not smtp_configured:
            session["message"] = "Warning: SMTP enabled but credentials are not fully configured in .env file!"

    # Update settings
    settings = get_or_create_settings(db)
    settings.max_attempts = max_attempts
    settings.smtp_enabled = smtp_enabled
    db.commit()

    session["message"] = "Settings updated successfully!"
    return redirect(url_for("admin.admin_settings"))
