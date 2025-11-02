import json

from functools import wraps
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session

from app.mail import SMTPMailer
from app.database import SessionLocal
from app.models import User, Quiz, Result
from app.utils import get_current_user, get_max_attempts, is_smtp_enabled, load_quiz_by_id, calculate_score

user = Blueprint('user', __name__, url_prefix='/user')

def with_db(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        db = SessionLocal()
        try:
            return f(db, *args, **kwargs)
        finally:
            db.close()
    return decorated_function

@user.route("/register", methods=["GET", "POST"])
@with_db
def user_register(db):
    """User registration/login page and handler"""
    if request.method == "POST":
        user_id = request.form.get("user_id", "").strip()
        password = request.form.get("password", "").strip()

        if not user_id or len(user_id) == 0:
            return render_template("user/register.html", error="Student ID is required")

        if not password or len(password) == 0:
            return render_template("user/register.html", error="Password is required")

        # Check if user exists (only admin-created users can login)
        user = db.query(User).filter(User.user_id == user_id, User.role == "user").first()

        if not user:
            # User doesn't exist - show error
            return render_template("user/register.html", error="Invalid credentials. Please contact your administrator.")

        # Verify password
        if user.password != password:
            return render_template("user/register.html", error="Invalid credentials. Please contact your administrator.")

        # Set session
        session["user_id"] = user.id
        session["role"] = "user"

        return redirect(url_for("user.user_history"))

    return render_template("user/register.html", error=None)


@user.route("/history")
@with_db
def user_history(db):
    """Display user's quiz history"""
    try:
        # Check if user is logged in
        if session.get("role") != "user":
            return redirect(url_for("user.user_register"))

        # Get current user
        user = get_current_user(db)
        if not user:
            return redirect(url_for("user.user_register"))

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
        return render_template("user/history.html", username=username, quizzes=quizzes, results=results)
    except Exception as e:
        print(f"ERROR in user_history: {str(e)}")
        import traceback
        traceback.print_exc()
        return f"<h1>Error loading history</h1><p>{str(e)}</p>", 500


@user.route("/quiz/<int:quiz_id>")
@with_db
def take_quiz(db, quiz_id):
    """Display quiz for user"""
    try:
        # Check if user is logged in
        if session.get("role") != "user":
            return redirect(url_for("user.user_register"))

        # Get current user
        user = get_current_user(db)
        if not user:
            return redirect(url_for("user.user_register"))

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
            return redirect(url_for("user.view_result", result_id=latest_result.id))

        attempt_number = attempt_count + 1

        # Load quiz
        quiz, quiz_data = load_quiz_by_id(quiz_id, db)
        if not quiz or not quiz_data:
            return "<h1>Quiz not found or unavailable.</h1>", 404

        return render_template("user/quiz.html", exam=quiz_data, quiz_id=quiz_id, attempt_number=attempt_number)
    except Exception as e:
        print(f"ERROR in take_quiz: {str(e)}")
        import traceback
        traceback.print_exc()
        return f"<h1>Error loading quiz</h1><p>{str(e)}</p>", 500


@user.route("/submit/<int:quiz_id>", methods=["POST"])
@with_db
def submit_quiz(db, quiz_id):
    """Handle quiz submission"""
    # Check if user is logged in
    if session.get("role") != "user":
        return redirect(url_for("user.user_register"))

    # Get current user
    user = get_current_user(db)
    if not user:
        return redirect(url_for("user.user_register"))

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
        return redirect(url_for("user.view_result", result_id=latest_result.id))

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
    email_sent = False
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
                email_sent = mailer.send_template(
                    to_email=user.email,
                    subject=f"Quiz Result: {quiz.title}",
                    template_name='quiz_result',
                    context=email_context
                )
            except Exception as e:
                print(f"Failed to send email: {str(e)}")
                email_sent = False
        else:
            print(f"SMTP is disabled. Email not sent to {user.email}")

    # Store email status in session for toast notification
    if email_sent:
        session["show_email_toast"] = True

    return redirect(url_for("user.view_result", result_id=result.id))


@user.route("/result/<int:result_id>")
@with_db
def view_result(db, result_id):
    """Display user's result by ID"""
    # Check if user is logged in
    if session.get("role") != "user":
        return redirect(url_for("user.user_register"))

    # Get current user
    user = get_current_user(db)
    if not user:
        return redirect(url_for("user.user_register"))

    # Get result from database
    result = db.query(Result).filter(Result.id == result_id, Result.user_id == user.id).first()
    if not result:
        return redirect(url_for("user.user_history"))

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

    # Check if we should show email toast
    show_email_toast = session.pop("show_email_toast", False)

    return render_template("user/result.html", score=result.score, results=results, exam_title=exam_title,
                         attempt_number=attempt_number, quiz_id=quiz_id, can_retake=can_retake, message=message,
                         show_email_toast=show_email_toast)

