from flask import Flask

from app.config import config, Config
from app.database import Base, engine

def create_app(config_name='default'):
    app = Flask(__name__,
                template_folder='templates',
                static_folder='static')

    # Load configuration
    app.config.from_object(config[config_name])
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_HTTPONLY=True
        )
    
    # load SECRET_KEY from environment variable
    app.config['SECRET_KEY'] = Config.SECRET_KEY

    # Import models to ensure they're registered with Base
    from app.models import User, Quiz, Result, Settings

    # Create database tables
    Base.metadata.create_all(bind=engine)

    # Register blueprints
    from app.blueprints.auth import auth
    from app.blueprints.user import user
    from app.blueprints.admin import admin

    app.register_blueprint(auth)
    app.register_blueprint(user)
    app.register_blueprint(admin)

    return app
