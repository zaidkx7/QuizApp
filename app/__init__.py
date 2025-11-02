from flask import Flask
from app.config import config
from app.database import Base, engine

def create_app(config_name='default'):
    app = Flask(__name__, 
                template_folder='templates',
                static_folder='static')
    
    # Load configuration
    app.config.from_object(config[config_name])
    
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
