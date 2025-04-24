from flask import current_app as app
from datetime import datetime
from app.model import db, User, Product
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func


class ReviewService:
    @staticmethod
    def create_review(user_id, comment, product_id=None, seller_id=None, rating=None):
        try:
            if product_id is None and seller_id is None:
                return False, "Either product_id or seller_id is required"

            if rating is None or not (1 <= rating <= 5):
                return False, "Rating must be between 1 and 5"
            from app.model import Review
            review = Review(
                user_id=user_id,
                product_id=product_id,
                seller_id=seller_id,
                rating=rating,
                comment=comment
            )
            db.session.add(review)
            db.session.commit()
            return True, "Review created successfully"
        except SQLAlchemyError as e:
            db.session.rollback()
            print(f"Error creating review: {e}")
            return False, str(e)

    @staticmethod
    def get_product_reviews(product_id):
        try:
            from app.model import Review
            return Review.query.filter_by(product_id=product_id).order_by(Review.review_date.desc()).all()
        except Exception as e:
            print(f"Error getting product reviews for {product_id}: {e}")
            return []

    @staticmethod
    def get_seller_reviews(seller_id):
        try:
            from app.model import Review
            return Review.query.filter_by(seller_id=seller_id).order_by(Review.review_date.desc()).all()
        except Exception as e:
             print(f"Error getting seller reviews for {seller_id}: {e}")
             return []

    @staticmethod
    def get_user_reviews(user_id, limit=None):
        try:
            from app.model import Review
            query = Review.query.filter_by(user_id=user_id).order_by(Review.review_date.desc())
            if limit:
                query = query.limit(limit)
            return query.all()
        except Exception as e:
            print(f"Error getting user reviews for {user_id}: {e}")
            return []

    @staticmethod
    def get_avg_rating_product(product_id):
        try:
            from app.model import Review
            result = db.session.query(
                func.avg(Review.rating).label('average'),
                func.count(Review.review_id).label('count')
            ).filter(Review.product_id == product_id).first()

            if result and result.count > 0:
                return float(result.average) if result.average else 0.0, result.count
            else:
                return 0.0, 0
        except Exception as e:
            print(f"Error getting avg rating for product {product_id}: {e}")
            return 0.0, 0

    @staticmethod
    def get_rating_distribution(product_id):
        distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        try:
            from app.model import Review
            results = db.session.query(
                Review.rating,
                func.count(Review.review_id).label('count')
            ).filter(Review.product_id == product_id).group_by(Review.rating).all()

            for rating, count in results:
                if rating in distribution:
                    distribution[rating] = count
            return distribution
        except Exception as e:
             print(f"Error getting rating distribution for product {product_id}: {e}")
             return distribution

    @staticmethod
    def get_avg_rating_seller(seller_id):
        try:
            from app.model import Review
            result = db.session.query(
                func.avg(Review.rating).label('average'),
                func.count(Review.review_id).label('count')
            ).filter(Review.seller_id == seller_id).first()

            if result and result.count > 0:
                return float(result.average) if result.average else 0.0, result.count
            else:
                return 0.0, 0
        except Exception as e:
            print(f"Error getting avg rating for seller {seller_id}: {e}")
            return 0.0, 0

    @staticmethod
    def get_rating_distribution_seller(seller_id):
        distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        try:
            from app.model import Review
            results = db.session.query(
                Review.rating,
                func.count(Review.review_id).label('count')
            ).filter(Review.seller_id == seller_id).group_by(Review.rating).all()

            for rating, count in results:
                if rating in distribution:
                    distribution[rating] = count
            return distribution
        except Exception as e:
             print(f"Error getting rating distribution for seller {seller_id}: {e}")
             return distribution

    @staticmethod
    def update_review(review_id, user_id, comment, rating):
        try:
            from app.model import Review
            review = Review.query.get(review_id)
            if not review:
                 return False, "Review not found"
            if review.user_id != user_id:
                 return False, "Permission denied"
            if rating is None or not (1 <= rating <= 5):
                 return False, "Invalid rating"

            review.comment = comment
            review.rating = rating
            review.review_date = datetime.utcnow() # Update timestamp
            db.session.commit()
            return True, "Review updated"
        except SQLAlchemyError as e:
            db.session.rollback()
            print(f"Error updating review {review_id}: {e}")
            return False, str(e)

    @staticmethod
    def delete_review(review_id, user_id):
        try:
            from app.model import Review
            review = Review.query.get(review_id)
            if not review:
                 return False, "Review not found"
            if review.user_id != user_id: # Ensure user owns the review
                 return False, "Permission denied"

            db.session.delete(review)
            db.session.commit()
            return True, "Review deleted"
        except SQLAlchemyError as e:
            db.session.rollback()
            print(f"Error deleting review {review_id}: {e}")
            return False, str(e)