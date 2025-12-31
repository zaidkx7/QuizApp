from flask import Blueprint, render_template, session, redirect, url_for

auth = Blueprint('auth', __name__)


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


@auth.route("/logout")
def logout():
    """Logout user"""
    session.clear()
    return redirect(url_for("auth.index"))
