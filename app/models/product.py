# app/models/product.py
from flask import current_app as app

class ProductService:
    @staticmethod
    def get_product(product_id):
        """Get a product by ID"""
        rows = app.db.execute('''
        SELECT product_id, owner_id, product_name, description, category_id, 
               price, image, created_at, updated_at
        FROM Products 
        WHERE product_id = :product_id
        ''', product_id=product_id)
        
        return rows[0] if rows else None
    
    @staticmethod
    def get_products(search_query=None, category_id=None, sort_by="name", sort_order="asc", page=1, per_page=12):
        """Get products with filtering and pagination"""
        query = '''
        SELECT p.product_id, p.product_name, p.description, p.price, p.image,
               p.category_id, c.category_name, p.owner_id,
               CONCAT(a.first_name, ' ', a.last_name) as seller_name
        FROM Products p
        JOIN Products_Categories c ON p.category_id = c.category_id
        JOIN Accounts a ON p.owner_id = a.user_id
        WHERE 1=1
        '''
        
        params = {}
        
        if search_query:
            query += ''' AND (LOWER(p.product_name) LIKE LOWER(:search) 
                       OR LOWER(p.description) LIKE LOWER(:search))'''
            params['search'] = f'%{search_query}%'
        
        if category_id:
            query += ' AND p.category_id = :category_id'
            params['category_id'] = category_id
        
        # Add sorting
        if sort_by == "name":
            query += f' ORDER BY p.product_name {sort_order}'
        elif sort_by == "price":
            query += f' ORDER BY p.price {sort_order}'
        elif sort_by == "newest":
            query += ' ORDER BY p.created_at DESC'
        
        # Add pagination
        query += ' LIMIT :per_page OFFSET :offset'
        params['per_page'] = per_page
        params['offset'] = (page - 1) * per_page
        
        return app.db.execute(query, **params)
    
    @staticmethod
    def get_categories():
        """Get all product categories"""
        return app.db.execute('''
        SELECT category_id, category_name 
        FROM Products_Categories
        ORDER BY category_name
        ''')