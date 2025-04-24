# app/models/product.py
from flask import current_app as app
from app.model import db, Product, ProductCategory, User
from sqlalchemy import func, or_
class ProductService:
    @staticmethod
    def get_product(product_id):
        product = db.session.get(Product, product_id)

        if product:
                    
            return {
                'product_id': product.product_id,
                'owner_id': product.owner_id,
                'product_name': product.product_name,
                'description': product.description,
                'category_id': product.category_id,
                'price': float(product.price) if product.price is not None else None,
                'image': product.image,
                'created_at': product.created_at,
                'updated_at': product.updated_at,
                'category_name': product.category.category_name if product.category else None,
                'owner_name': f"{product.owner.first_name} {product.owner.last_name}" if product.owner else None
            }
        else:
            return None # Return None if not found

    
    @staticmethod
    def get_products(search_query=None, category_id=None, sort_by="name", sort_dir="asc", page=1, per_page=12):
        """Get products with filtering and pagination using SQLAlchemy"""
        query = Product.query.join(ProductCategory).join(User, Product.owner_id == User.user_id)

        if search_query:
             search_term = f'%{search_query.lower()}%'
             # Use or_ for searching multiple fields
             query = query.filter(
                 or_(
                     func.lower(Product.product_name).like(search_term),
                     func.lower(Product.description).like(search_term)
                 )
             )

        if category_id:
            query = query.filter(Product.category_id == category_id)

        # Add sorting
        order_column = Product.product_name
        if sort_by == "price":
            order_column = Product.price
        elif sort_by == "newest":
            order_column = Product.created_at

        if sort_dir == "desc":
            query = query.order_by(order_column.desc())
        else:
            query = query.order_by(order_column.asc())

        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        return pagination

    @staticmethod
    def get_categories():
        categories = ProductCategory.query.order_by(ProductCategory.category_name).all()
        return [{'category_id': c.category_id, 'category_name': c.category_name} for c in categories]
