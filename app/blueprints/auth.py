from flask import Blueprint, render_template, session, redirect, url_for, request, current_app
from werkzeug.utils import secure_filename
import os
from functools import wraps

from app.database import SessionLocal
from app.utils import get_current_user

auth = Blueprint('auth', __name__)

def with_db(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        db = SessionLocal()
        try:
            return f(db, *args, **kwargs)
        finally:
            db.close()
    return decorated_function

@auth.route("/")
def index():
    """Landing page with smart redirect"""
    # Check if user is logged in as admin
    if session.get("role") == "admin":
        return redirect(url_for("admin.admin_dashboard"))
    
    # Check if user is logged in as student
    if session.get("role") == "user":
        return redirect(url_for("user.user_history"))
        
    return render_template("index.html")


@auth.route("/profile", methods=["GET", "POST"])
@with_db
def profile(db):
    """User profile management"""
    if not session.get("user_id"):
        return redirect(url_for("auth.index"))

    user = get_current_user(db)
    if not user:
        session.clear()
        return redirect(url_for("auth.index"))

    if request.method == "POST":
        # Update text fields
        user.first_name = request.form.get("first_name", "").strip()
        user.last_name = request.form.get("last_name", "").strip()
        user.email = request.form.get("email", "").strip()
        
        # Handle Password Change
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        
        if new_password:
            if new_password == confirm_password:
                user.password = new_password # In a real app, hash this!
                # You might want to flash a success message here
            else:
                # Handle password mismatch error (flash message ideal)
                pass 

        # Handle Profile Picture
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and file.filename:
                filename = secure_filename(file.filename)
                # Make unique to avoid caching issues or overwrites
                import uuid
                unique_filename = f"{uuid.uuid4()}_{filename}"
                
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'profiles')
                os.makedirs(upload_folder, exist_ok=True)
                
                file.save(os.path.join(upload_folder, unique_filename))
                
                # Delete old pic if exists and not default?
                # For now just update reference
                user.profile_pic = unique_filename

        db.commit()
        
        # Update Session
        session["full_name"] = user.full_name
        if user.profile_pic:
            session["profile_pic"] = user.profile_pic
            
        return redirect(url_for("auth.profile"))

    return render_template("profile.html", user=user)


@auth.route("/logout")
def logout():
    """Logout user"""
    session.clear()
    return redirect(url_for("auth.index"))
