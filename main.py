from fastapi import FastAPI, Request, Form, UploadFile, File, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
import json
import os
import re
from datetime import datetime
from typing import Optional
from rapidfuzz import fuzz

from database import engine, get_db, Base
from models import User, Result, Quiz

# Create database tables
Base.metadata.create_all(bind=engine)

# Initialize FastAPI app
app = FastAPI(title="Quiz App")

# Add session middleware
# IMPORTANT: Change this secret key before deploying to production!
# Generate with: python3 -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY = "689eaa035980f7a2f09caaef195600c3b8f589a1a36cc696dae3425fefe587d5"
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup templates
templates = Jinja2Templates(directory="templates")

# Admin credentials
ADMIN_USERNAME = "zaid.sh"
ADMIN_PASSWORD = "admin@zaid.sh"


# Helper functions
def get_current_user(request: Request, db: Session):
    """Get current user from session"""
    user_id = request.session.get("user_id")
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
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Landing page"""
    return templates.TemplateResponse("index.html", {"request": request})




@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    """Admin login page"""
    return templates.TemplateResponse("admin_login.html", {"request": request, "error": None})


@app.post("/admin/login")
async def admin_login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    """Handle admin login"""
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        # Check if admin user exists in DB, if not create it
        admin_user = db.query(User).filter(User.username == ADMIN_USERNAME, User.role == "admin").first()
        if not admin_user:
            admin_user = User(username=ADMIN_USERNAME, role="admin")
            db.add(admin_user)
            db.commit()
            db.refresh(admin_user)

        # Set session
        request.session["user_id"] = admin_user.id
        request.session["role"] = "admin"
        return RedirectResponse(url="/admin/dashboard", status_code=303)

    return templates.TemplateResponse("admin_login.html", {"request": request, "error": "Invalid credentials"})


@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    """Admin dashboard"""
    # Check if user is admin
    if request.session.get("role") != "admin":
        return RedirectResponse(url="/admin/login", status_code=303)

    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "message": request.session.pop("message", None)
    })


@app.get("/admin/quizzes", response_class=HTMLResponse)
async def admin_quizzes(request: Request, db: Session = Depends(get_db)):
    """Manage quizzes page"""
    # Check if user is admin
    if request.session.get("role") != "admin":
        return RedirectResponse(url="/admin/login", status_code=303)

    # Get all quizzes
    quizzes = db.query(Quiz).order_by(Quiz.created_at.desc()).all()

    return templates.TemplateResponse("admin_quizzes.html", {
        "request": request,
        "quizzes": quizzes,
        "message": request.session.pop("message", None)
    })


@app.post("/admin/quiz/upload")
async def upload_quiz(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Handle quiz file upload"""
    # Check if user is admin
    if request.session.get("role") != "admin":
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        # Read and parse JSON
        content = await file.read()
        quiz_data = json.loads(content)

        # Validate JSON structure
        required_keys = ["title"]
        if not all(key in quiz_data for key in required_keys):
            request.session["message"] = "Invalid quiz format - must have 'title' field"
            return RedirectResponse(url="/admin/quizzes", status_code=303)

        # Generate unique filename
        import time
        filename = f"quiz_{int(time.time())}_{file.filename}"

        # Save to questions folder
        os.makedirs("questions", exist_ok=True)
        quiz_path = f"questions/{filename}"
        with open(quiz_path, "w", encoding="utf-8") as f:
            json.dump(quiz_data, f, indent=2)

        # Create Quiz record in database
        is_first_quiz = db.query(Quiz).count() == 0
        new_quiz = Quiz(
            title=quiz_data["title"],
            filename=filename,
            is_active=is_first_quiz  # Auto-activate if it's the first quiz
        )
        db.add(new_quiz)
        db.commit()

        request.session["message"] = f"Quiz '{quiz_data['title']}' uploaded successfully!"
        return RedirectResponse(url="/admin/quizzes", status_code=303)

    except json.JSONDecodeError:
        request.session["message"] = "Invalid JSON file"
        return RedirectResponse(url="/admin/quizzes", status_code=303)
    except Exception as e:
        request.session["message"] = f"Error uploading quiz: {str(e)}"
        return RedirectResponse(url="/admin/quizzes", status_code=303)


@app.post("/admin/quiz/set-active/{quiz_id}")
async def set_active_quiz(request: Request, quiz_id: int, db: Session = Depends(get_db)):
    """Set a quiz as active"""
    # Check if user is admin
    if request.session.get("role") != "admin":
        return RedirectResponse(url="/admin/login", status_code=303)

    # Deactivate all quizzes
    db.query(Quiz).update({"is_active": False})

    # Activate the selected quiz
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if quiz:
        quiz.is_active = True
        db.commit()
        request.session["message"] = f"Quiz '{quiz.title}' is now active!"
    else:
        request.session["message"] = "Quiz not found"

    return RedirectResponse(url="/admin/quizzes", status_code=303)


@app.post("/admin/quiz/delete/{quiz_id}")
async def delete_quiz(request: Request, quiz_id: int, db: Session = Depends(get_db)):
    """Delete a quiz and its submissions"""
    # Check if user is admin
    if request.session.get("role") != "admin":
        return RedirectResponse(url="/admin/login", status_code=303)

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

        request.session["message"] = f"Quiz '{quiz.title}' deleted successfully!"
    else:
        request.session["message"] = "Quiz not found"

    return RedirectResponse(url="/admin/quizzes", status_code=303)


@app.get("/admin/scores", response_class=HTMLResponse)
async def view_scores(request: Request, db: Session = Depends(get_db)):
    """View all user scores"""
    # Check if user is admin
    if request.session.get("role") != "admin":
        return RedirectResponse(url="/admin/login", status_code=303)

    # Get all results with user info
    results = db.query(Result).join(User).order_by(Result.submitted_at.desc()).all()

    return templates.TemplateResponse("scores.html", {
        "request": request,
        "results": results
    })


@app.get("/user/register", response_class=HTMLResponse)
async def user_register_page(request: Request):
    """User registration/login page"""
    return templates.TemplateResponse("user_register.html", {"request": request, "error": None})


@app.post("/user/register")
async def user_register(request: Request, user_id: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    """Handle user registration/login"""
    if not user_id or len(user_id.strip()) == 0:
        return templates.TemplateResponse("user_register.html", {"request": request, "error": "Student ID is required"})

    if not password or len(password.strip()) == 0:
        return templates.TemplateResponse("user_register.html", {"request": request, "error": "Password is required"})

    user_id = user_id.strip()
    password = password.strip()

    # Check if user exists (only admin-created users can login)
    user = db.query(User).filter(User.user_id == user_id, User.role == "user").first()

    if not user:
        # User doesn't exist - show error
        return templates.TemplateResponse("user_register.html", {"request": request, "error": "Invalid credentials. Please contact your administrator."})

    # Verify password
    if user.password != password:
        return templates.TemplateResponse("user_register.html", {"request": request, "error": "Invalid credentials. Please contact your administrator."})

    # Set session
    request.session["user_id"] = user.id
    request.session["role"] = "user"

    return RedirectResponse(url="/user/history", status_code=303)


@app.get("/user/history", response_class=HTMLResponse)
async def user_history(request: Request, db: Session = Depends(get_db)):
    """Display user's quiz history"""
    try:
        # Check if user is logged in
        if request.session.get("role") != "user":
            return RedirectResponse(url="/user/register", status_code=303)

        # Get current user
        user = get_current_user(request, db)
        if not user:
            return RedirectResponse(url="/user/register", status_code=303)

        # Get all quizzes with user's submissions
        quizzes = db.query(Quiz).order_by(Quiz.is_active.desc(), Quiz.created_at.desc()).all()

        # For each quiz, attach user's submission if exists
        for quiz in quizzes:
            quiz.user_submissions = [r for r in quiz.results if r.user_id == user.id]

        # Get all user's results
        results = db.query(Result).filter(Result.user_id == user.id).order_by(Result.submitted_at.desc()).all()

        return templates.TemplateResponse("user_history.html", {
            "request": request,
            "username": user.user_id if user.user_id else user.username,
            "quizzes": quizzes,
            "results": results
        })
    except Exception as e:
        print(f"ERROR in user_history: {str(e)}")
        import traceback
        traceback.print_exc()
        return HTMLResponse(f"<h1>Error loading history</h1><p>{str(e)}</p>", status_code=500)


@app.get("/user/quiz/{quiz_id}", response_class=HTMLResponse)
async def take_quiz(request: Request, quiz_id: int, db: Session = Depends(get_db)):
    """Display quiz for user"""
    try:
        # Check if user is logged in
        if request.session.get("role") != "user":
            return RedirectResponse(url="/user/register", status_code=303)

        # Get current user
        user = get_current_user(request, db)
        if not user:
            return RedirectResponse(url="/user/register", status_code=303)

        # Check if user already submitted this quiz
        existing_submission = db.query(Result).filter(
            Result.user_id == user.id,
            Result.quiz_id == quiz_id
        ).first()

        if existing_submission:
            request.session["message"] = "You have already submitted this quiz!"
            return RedirectResponse(url=f"/user/result/{existing_submission.id}", status_code=303)

        # Load quiz
        quiz, quiz_data = load_quiz_by_id(quiz_id, db)
        if not quiz or not quiz_data:
            return HTMLResponse("<h1>Quiz not found or unavailable.</h1>")

        return templates.TemplateResponse("quiz.html", {
            "request": request,
            "exam": quiz_data,
            "quiz_id": quiz_id
        })
    except Exception as e:
        print(f"ERROR in take_quiz: {str(e)}")
        import traceback
        traceback.print_exc()
        return HTMLResponse(f"<h1>Error loading quiz</h1><p>{str(e)}</p>", status_code=500)


@app.post("/user/submit/{quiz_id}")
async def submit_quiz(request: Request, quiz_id: int, db: Session = Depends(get_db)):
    """Handle quiz submission"""
    # Check if user is logged in
    if request.session.get("role") != "user":
        return RedirectResponse(url="/user/register", status_code=303)

    # Get current user
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/user/register", status_code=303)

    # Check if user already submitted this quiz
    existing_submission = db.query(Result).filter(
        Result.user_id == user.id,
        Result.quiz_id == quiz_id
    ).first()

    if existing_submission:
        return RedirectResponse(url=f"/user/result/{existing_submission.id}", status_code=303)

    # Load quiz
    quiz, quiz_data = load_quiz_by_id(quiz_id, db)
    if not quiz or not quiz_data:
        return HTMLResponse("<h1>Quiz not found.</h1>")

    # Get form data
    form_data = await request.form()
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

    return RedirectResponse(url=f"/user/result/{result.id}", status_code=303)


@app.get("/user/result/{result_id}", response_class=HTMLResponse)
async def view_result(request: Request, result_id: int, db: Session = Depends(get_db)):
    """Display user's result by ID"""
    # Check if user is logged in
    if request.session.get("role") != "user":
        return RedirectResponse(url="/user/register", status_code=303)

    # Get current user
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/user/register", status_code=303)

    # Get result from database
    result = db.query(Result).filter(Result.id == result_id, Result.user_id == user.id).first()
    if not result:
        return RedirectResponse(url="/user/history", status_code=303)

    # Parse results from JSON
    results = json.loads(result.answers)

    # Get quiz title from relationship
    exam_title = result.quiz.title if result.quiz else "Exam"

    return templates.TemplateResponse("result.html", {
        "request": request,
        "score": result.score,
        "results": results,
        "exam_title": exam_title
    })


@app.get("/admin/quiz/preview/{quiz_id}", response_class=HTMLResponse)
async def admin_quiz_preview(request: Request, quiz_id: int, db: Session = Depends(get_db)):
    """Preview a quiz with correct answers"""
    # Check if user is admin
    if request.session.get("role") != "admin":
        return RedirectResponse(url="/admin/login", status_code=303)

    # Load quiz
    quiz, quiz_data = load_quiz_by_id(quiz_id, db)
    if not quiz or not quiz_data:
        return HTMLResponse("<h1>Quiz not found.</h1>")

    return templates.TemplateResponse("admin_quiz_preview.html", {
        "request": request,
        "exam": quiz_data
    })


@app.get("/admin/submission/{result_id}", response_class=HTMLResponse)
async def admin_view_submission(request: Request, result_id: int, db: Session = Depends(get_db)):
    """View a specific user's submission"""
    # Check if user is admin
    if request.session.get("role") != "admin":
        return RedirectResponse(url="/admin/login", status_code=303)

    # Get result from database
    result = db.query(Result).filter(Result.id == result_id).first()
    if not result:
        return RedirectResponse(url="/admin/scores", status_code=303)

    # Parse results from JSON
    results = json.loads(result.answers)

    # Get quiz title from relationship
    exam_title = result.quiz.title if result.quiz else "Exam"

    return templates.TemplateResponse("admin_user_submission.html", {
        "request": request,
        "username": result.user.username,
        "score": result.score,
        "results": results,
        "exam_title": exam_title,
        "submitted_at": result.submitted_at.strftime('%B %d, %Y at %I:%M %p')
    })


@app.post("/admin/submissions/delete-all")
async def admin_delete_all_submissions(request: Request, db: Session = Depends(get_db)):
    """Delete all student submissions"""
    # Check if user is admin
    if request.session.get("role") != "admin":
        return RedirectResponse(url="/admin/login", status_code=303)

    # Delete all results
    db.query(Result).delete()
    db.commit()

    request.session["message"] = "All submissions deleted successfully!"
    return RedirectResponse(url="/admin/dashboard", status_code=303)


@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users(request: Request, db: Session = Depends(get_db)):
    """Manage users page"""
    # Check if user is admin
    if request.session.get("role") != "admin":
        return RedirectResponse(url="/admin/login", status_code=303)

    # Get all users (excluding admin)
    users = db.query(User).filter(User.role == "user").order_by(User.user_id).all()

    return templates.TemplateResponse("admin_users.html", {
        "request": request,
        "users": users,
        "message": request.session.pop("message", None)
    })


@app.post("/admin/users/add")
async def admin_add_user(request: Request, user_id: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    """Add a new user"""
    # Check if user is admin
    if request.session.get("role") != "admin":
        return RedirectResponse(url="/admin/login", status_code=303)

    # Check if user already exists
    existing_user = db.query(User).filter(User.user_id == user_id).first()
    if existing_user:
        request.session["message"] = f"User with ID {user_id} already exists!"
        return RedirectResponse(url="/admin/users", status_code=303)

    # Create new user
    new_user = User(
        username=f"Student_{user_id}",
        user_id=user_id,
        password=password,
        role="user"
    )
    db.add(new_user)
    db.commit()

    request.session["message"] = f"User {user_id} added successfully!"
    return RedirectResponse(url="/admin/users", status_code=303)


@app.post("/admin/users/edit")
async def admin_edit_user(request: Request, user_db_id: int = Form(...), user_id: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    """Edit a user"""
    # Check if user is admin
    if request.session.get("role") != "admin":
        return RedirectResponse(url="/admin/login", status_code=303)

    # Get user
    user = db.query(User).filter(User.id == user_db_id).first()
    if not user:
        request.session["message"] = "User not found!"
        return RedirectResponse(url="/admin/users", status_code=303)

    # Check if new user_id conflicts with another user
    existing_user = db.query(User).filter(User.user_id == user_id, User.id != user_db_id).first()
    if existing_user:
        request.session["message"] = f"User ID {user_id} is already taken!"
        return RedirectResponse(url="/admin/users", status_code=303)

    # Update user
    user.user_id = user_id
    user.password = password
    user.username = f"Student_{user_id}"
    db.commit()

    request.session["message"] = f"User {user_id} updated successfully!"
    return RedirectResponse(url="/admin/users", status_code=303)


@app.post("/admin/users/delete/{user_db_id}")
async def admin_delete_user(request: Request, user_db_id: int, db: Session = Depends(get_db)):
    """Delete a user and their submissions"""
    # Check if user is admin
    if request.session.get("role") != "admin":
        return RedirectResponse(url="/admin/login", status_code=303)

    # Get user
    user = db.query(User).filter(User.id == user_db_id).first()
    if not user:
        request.session["message"] = "User not found!"
        return RedirectResponse(url="/admin/users", status_code=303)

    # Delete user's results first
    db.query(Result).filter(Result.user_id == user_db_id).delete()

    # Delete user
    db.delete(user)
    db.commit()

    request.session["message"] = "User deleted successfully!"
    return RedirectResponse(url="/admin/users", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    """Logout user"""
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
