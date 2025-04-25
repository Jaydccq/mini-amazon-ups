#!/usr/bin/env python
# filepath: /Users/hongxichen/Desktop/amazon-ups/reset_admin_password.py

import os
import sys
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError

# Setup logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Get database connection string from environment variable or use default
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:abc123@localhost:5432/mini_amazon')

def import_user_model():
    """Dynamically import the User model from the application."""
    project_root = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.join(project_root, 'app')
    
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
        sys.path.insert(0, project_root)
    
    try:
        from app.model import User
        return User
    except ImportError as e:
        logger.error(f"Error importing User model: {e}")
        sys.exit(1)

def reset_admin_password(session, admin_email='admin@example.com', password='admin'):
    """
    Reset password for existing admin user or create if doesn't exist
    
    Args:
        session: SQLAlchemy session
        admin_email: Email for admin user
        password: New password to set
        
    Returns:
        Tuple of (admin_user, status_message)
    """
    User = import_user_model()
    
    # Check if admin exists
    admin = session.query(User).filter_by(email=admin_email).first()
    
    if admin:
        # Update password for existing admin
        admin.set_password(password)
        status = "updated"
        logger.info(f"Updating password for existing admin user: {admin_email}")
    else:
        # Admin doesn't exist, create one
        logger.warning(f"Admin user {admin_email} not found. Creating new admin.")
        admin = User(email=admin_email, first_name='Admin', 
                    last_name='User', is_seller=True)
        admin.set_password(password)
        session.add(admin)
        status = "created"
    
    try:
        session.commit()
        logger.info(f"Successfully {status} admin user with email {admin_email}")
        return admin, status
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Failed to update admin user: {e}")
        return None, f"error: {str(e)}"

def main():
    """Main function when script is run directly."""
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description='Reset admin user password')
    parser.add_argument('--email', default='admin@example.com', help='Admin email address')
    parser.add_argument('--password', default='admin', help='New admin password')
    args = parser.parse_args()
    
    # Setup database connection
    try:
        engine = create_engine(DATABASE_URL)
        Session = sessionmaker(bind=engine)
        session = Session()
        logger.info(f"Connected to database: {DATABASE_URL.split('@')[-1]}")
    except SQLAlchemyError as e:
        logger.error(f"Failed to connect to database: {e}")
        sys.exit(1)
        
    # Reset admin password
    admin, status = reset_admin_password(
        session, 
        admin_email=args.email,
        password=args.password
    )
    
    if admin:
        logger.info(f"Admin user password {status}")
        logger.info(f"Admin ID: {admin.user_id if hasattr(admin, 'user_id') else 'N/A'}")
        logger.info(f"You should now be able to login with:")
        logger.info(f"  Email: {args.email}")
        logger.info(f"  Password: {args.password}")
    else:
        logger.error("Failed to reset admin password")
    
    # Close session
    session.close()
    
if __name__ == "__main__":
    main()