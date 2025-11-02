from flask import Blueprint, render_template, session, redirect, url_for

auth = Blueprint('auth', __name__)


@auth.route("/")
def index():
    """Landing page"""
    return render_template("index.html")


@auth.route("/logout")
def logout():
    """Logout user"""
    session.clear()
    return redirect(url_for("auth.index"))
