import os
from flask import Flask, current_app
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
import logging

from app.model import db, User, ProductCategory
from app.controllers.seller_controller import seller_bp
from app.controllers.amazon_controller import amazon_bp, api_bp, admin_bp
from app.controllers.webhook_controller import world_bp, ups_bp
from app.controllers.cart_controller import bp as cart_bp
from app.controllers.review_controller import bp as review_bp
from app.services.amazon_exposed_api import ups_webhooks
from app.services.world_simulator_service import WorldSimulatorService

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)

    if test_config is None:
        if not os.environ.get('DATABASE_URL'):
            database_url = 'postgresql://postgres:abc123@localhost:5432/mini_amazon'
        else:
            database_url = os.environ.get('DATABASE_URL')

        app.config.from_mapping(
            SECRET_KEY=os.environ.get('SECRET_KEY', 'dev'),
            SQLALCHEMY_DATABASE_URI=database_url,
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            UPLOAD_FOLDER=os.path.join(app.instance_path, 'uploads'),
            MAX_CONTENT_LENGTH=16 * 1024 * 1024,
            WORLD_HOST=os.environ.get('WORLD_HOST', 'world-simulator'),
            WORLD_PORT=int(os.environ.get('WORLD_PORT', '23456')),
            PORT=int(os.environ.get('PORT', 8080))
        )
    else:
        app.config.from_mapping(test_config)

    try:
        os.makedirs(app.instance_path)
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    except OSError:
        pass

    db.init_app(app)

    app.register_blueprint(amazon_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(world_bp)
    app.register_blueprint(ups_bp)
    app.register_blueprint(cart_bp)
    app.register_blueprint(review_bp)
    app.register_blueprint(seller_bp)
    app.register_blueprint(ups_webhooks)

    migrate = Migrate(app, db)
    csrf = CSRFProtect(app)

    csrf.exempt(ups_webhooks)

    login_manager = LoginManager(app)
    login_manager.login_view = 'amazon.login'

    @login_manager.user_loader
    def load_user(user_id):
         # Use a temporary app context if needed for the query
         # Although login_manager callbacks usually run within a request context
         with app.app_context():
              return User.query.get(int(user_id))

    with app.app_context():
        db.create_all()

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

            category = ProductCategory.query.filter_by(category_name='General').first()
            if not category:
                category = ProductCategory(category_name='General')
                db.session.add(category)

            try:
                 db.session.commit()
            except Exception as e:
                 db.session.rollback()
                 app.logger.error(f"Error committing default admin/category: {e}")


        try:
            world_simulator_service = WorldSimulatorService(
                app=app,
                host=app.config.get('WORLD_HOST'),
                port=app.config.get('WORLD_PORT')
            )
            app.config['DEFAULT_SIM_SPEED'] = 3001
            app.config['WORLD_SIMULATOR_SERVICE'] = world_simulator_service
            app.logger.info(f"WorldSimulatorService initialized and stored (Host: {app.config.get('WORLD_HOST')}, Port: {app.config.get('WORLD_PORT')})")
        except Exception as e:
            app.logger.error(f"Failed to initialize WorldSimulatorService: {e}", exc_info=True)
            app.config['WORLD_SIMULATOR_SERVICE'] = None # Ensure it's None if failed

    return app 

app = create_app()