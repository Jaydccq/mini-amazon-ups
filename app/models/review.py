# app/models/review.py
from flask import current_app as app
from datetime import datetime
from app.model import db, User, Product
from sqlalchemy.exc import SQLAlchemyError

class ReviewService:
    @staticmethod
    def create_review(user_id, comment, product_id=None, seller_id=None, rating=None):
        """Create a new product or seller review"""
        try:
            if product_id is None and seller_id is None:
                return False, "Either product_id or seller_id is required"
            
            if rating is None or not (1 <= rating <= 5):
                return False, "Rating must be between 1 and 5"
            
            # Create Review model for your database
            # This will depend on your database schema
            
            db.session.commit()
            return True, "Review created successfully"
        except SQLAlchemyError as e:
            db.session.rollback()
            return False, str(e)
    
    @staticmethod
    def get_product_reviews(product_id):
        """Get all reviews for a product"""
        try:
            # Query logic for your database
            # Return list of reviews
            pass
        except Exception as e:
            return []
    
    @staticmethod
    def get_seller_reviews(seller_id):
        """Get all reviews for a seller"""
        try:
            # Query logic for your database
            # Return list of reviews
            pass
        except Exception as e:
            return []
    
    @staticmethod
    def get_user_reviews(user_id, limit=None):
        """Get reviews created by a user"""
        try:
            # Query logic for your database
            # Return list of reviews
            pass
        except Exception as e:
            return []