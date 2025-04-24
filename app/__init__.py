import os
from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from app.model import db, User

# Import blueprints
from app.controllers.amazon_controller import amazon_bp, api_bp, admin_bp
from app.controllers.webhook_controller import world_bp, ups_bp
from app.controllers.cart_controller import bp as cart_bp
from app.controllers.review_controller import bp as review_bp

def create_app(test_config=None):
    # Create and configure the app
    app = Flask(__name__, instance_relative_config=True)
    
    # Set up configuration
    if test_config is None:
        # For local development outside Docker
        if not os.environ.get('DATABASE_URL'):
            database_url = 'postgresql://postgres:abc123@localhost:5432/mini_amazon'  # Local connection with no username/password
        else:
            database_url = os.environ.get('DATABASE_URL')
        
        app.config.from_mapping(
            SECRET_KEY=os.environ.get('SECRET_KEY', 'dev'),
            SQLALCHEMY_DATABASE_URI=database_url,
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            UPLOAD_FOLDER=os.path.join(app.instance_path, 'uploads'),
            MAX_CONTENT_LENGTH=16 * 1024 * 1024  # 16MB max upload
        )
    else:
        # Load the test config if passed in
        app.config.from_mapping(test_config)
    
    # Ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    except OSError:
        pass
    
    # Initialize Flask extensions
    db.init_app(app)
    
    # Register blueprints - ONLY REGISTER ONCE
    app.register_blueprint(amazon_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(world_bp)
    app.register_blueprint(ups_bp)
    app.register_blueprint(cart_bp)
    app.register_blueprint(review_bp)
    
    # Setup Flask-Migrate
    migrate = Migrate(app, db)
    
    # Setup CSRF protection
    csrf = CSRFProtect(app)
    
    # Setup Flask-Login
    login_manager = LoginManager(app)
    login_manager.login_view = 'amazon.login'
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
    # Create tables if they don't exist
    with app.app_context():
        db.create_all()
        
        # Create default admin user if it doesn't exist
        admin = User.query.filter_by(email='admin@example.com').first()
        if not admin:
            admin = User(
                email='admin@example.com',
                first_name='Admin',
                last_name='User',
                is_seller=True
            )
            admin.set_password('admin')
            db.session.add(admin)
            
            # Create default product category
            from app.model import ProductCategory
            category = ProductCategory.query.filter_by(category_name='General').first()
            if not category:
                category = ProductCategory(category_name='General')
                db.session.add(category)
            
            db.session.commit()
    
    return app