from flask import current_app as app
from datetime import datetime


class Inventory:
    def __init__(self, inventory_id, seller_id, product_id, quantity, unit_price,
                 created_at, updated_at, owner_id=None, product_name=None, seller_name=None,
                 category_id=None, category_name=None, image=None):
        self.inventory_id = inventory_id
        self.seller_id = seller_id
        self.product_id = product_id
        self.quantity = quantity
        self.unit_price = unit_price
        self.created_at = created_at
        self.updated_at = updated_at
        self.owner_id = owner_id
        self.product_name = product_name
        self.seller_name = seller_name
        self.category_id = category_id
        self.category_name = category_name
        self.image = image

    @staticmethod
    def get(inventory_id):
        rows = app.db.execute('''
            SELECT i.inventory_id, i.seller_id, i.product_id, i.quantity, i.unit_price, 
                   i.created_at, i.updated_at, i.owner_id, p.product_name, CONCAT(a.first_name, ' ', a.last_name) AS seller_name,
                   p.category_id, pc.category_name, p.image
            FROM Inventory i
            JOIN Products p ON i.product_id = p.product_id
            JOIN Accounts a ON i.seller_id = a.user_id
            JOIN Products_Categories pc ON p.category_id = pc.category_id
            WHERE i.inventory_id = :inventory_id
        ''', inventory_id=inventory_id)

        return Inventory(*(rows[0])) if rows else None

    @staticmethod
    def get_by_seller_and_product(seller_id, product_id):
        rows = app.db.execute('''
            SELECT i.inventory_id, i.seller_id, i.product_id, i.quantity, i.unit_price, 
                   i.created_at, i.updated_at, p.product_name, CONCAT(a.first_name, ' ', a.last_name) AS seller_name,
                   p.category_id, pc.category_name, p.image
            FROM Inventory i
            JOIN Products p ON i.product_id = p.product_id
            JOIN Accounts a ON i.seller_id = a.user_id
            JOIN Products_Categories pc ON p.category_id = pc.category_id
            WHERE i.seller_id = :seller_id AND i.product_id = :product_id
        ''', seller_id=seller_id, product_id=product_id)

        return Inventory(*(rows[0])) if rows else None

    @staticmethod
    def get_for_seller(seller_id, limit=20, offset=0, search_query=None, category_id=None):
        query = '''
            SELECT i.inventory_id, i.seller_id, i.product_id, i.quantity, i.unit_price, 
                   i.created_at, i.updated_at, i.owner_id, p.product_name, CONCAT(a.first_name, ' ', a.last_name) AS seller_name,
                   p.category_id, pc.category_name, p.image
            FROM Inventory i
            JOIN Products p ON i.product_id = p.product_id
            JOIN Accounts a ON i.seller_id = a.user_id
            JOIN Products_Categories pc ON p.category_id = pc.category_id
            WHERE i.seller_id = :seller_id
        '''
        params = {'seller_id': seller_id}

        if search_query:
            query += " AND p.product_name ILIKE :search_query"
            params['search_query'] = f'%{search_query}%'

        if category_id:
            query += " AND p.category_id = :category_id"
            params['category_id'] = category_id

        query += " ORDER BY p.product_name LIMIT :limit OFFSET :offset"
        params['limit'] = limit
        params['offset'] = offset

        rows = app.db.execute(query, **params)
        return [Inventory(*row) for row in rows]

    @staticmethod
    def count_for_seller(seller_id, search_query=None, category_id=None):
        query = '''
            SELECT COUNT(*)
            FROM Inventory i
            JOIN Products p ON i.product_id = p.product_id
            WHERE i.seller_id = :seller_id
        '''
        params = {'seller_id': seller_id}

        if search_query:
            query += " AND p.product_name ILIKE :search_query"
            params['search_query'] = f'%{search_query}%'

        if category_id:
            query += " AND p.category_id = :category_id"
            params['category_id'] = category_id

        result = app.db.execute(query, **params)
        return result[0][0] if result else 0

    @staticmethod
    def create(seller_id, product_id, quantity, unit_price):
        try:
            owner_rows = app.db.execute('''
                SELECT owner_id FROM Products WHERE product_id = :product_id
            ''', product_id=product_id)

            if not owner_rows:
                return None

            owner_id = owner_rows[0][0]

            inventory_id = app.db.execute('''
                INSERT INTO Inventory (seller_id, product_id, quantity, unit_price, owner_id)
                VALUES (:seller_id, :product_id, :quantity, :unit_price, :owner_id)
                RETURNING inventory_id
            ''', seller_id=seller_id, product_id=product_id,
                                          quantity=quantity, unit_price=unit_price, owner_id=owner_id)

            return inventory_id[0][0] if inventory_id else None
        except Exception as e:
            print(f"Error creating inventory: {e}")
            return None

    @staticmethod
    def to_dict(self):
        return {
            'inventory_id': self.inventory_id,
            'seller_id': self.seller_id,
            'seller_name': self.seller_name,
            'unit_price': float(self.unit_price),
            'quantity': self.quantity,
            'product_id': self.product_id,
            'product_name': self.product_name,
            'category_id': self.category_id,
            'category_name': self.category_name,
            'image': self.image,
            'owner_id': self.owner_id,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None
        }

    @staticmethod
    def update(inventory_id, seller_id, quantity=None, unit_price=None):
        """Update inventory quantity or price"""
        try:
            update_parts = []
            params = {'inventory_id': inventory_id, 'seller_id': seller_id}

            if quantity is not None:
                update_parts.append("quantity = :quantity")
                params['quantity'] = quantity

            if unit_price is not None:
                update_parts.append("unit_price = :unit_price")
                params['unit_price'] = unit_price

            if update_parts:
                update_parts.append("updated_at = :updated_at")
                params['updated_at'] = datetime.utcnow()

                query = f'''
                    UPDATE Inventory 
                    SET {", ".join(update_parts)}
                    WHERE inventory_id = :inventory_id AND seller_id = :seller_id
                    RETURNING inventory_id
                '''

                result = app.db.execute(query, **params)
                return result[0][0] if result else None
            return None

        except Exception as e:
            print(f"Error updating inventory: {e}")
            return None

    @staticmethod
    def delete(inventory_id, seller_id):
        """Remove a product from seller's inventory"""
        try:
            result = app.db.execute('''
                DELETE FROM Inventory 
                WHERE inventory_id = :inventory_id AND seller_id = :seller_id
                RETURNING inventory_id
            ''', inventory_id=inventory_id, seller_id=seller_id)

            return result[0][0] if result else None
        except Exception as e:
            print(f"Error deleting inventory: {e}")
            return None

    @staticmethod
    def get_sellers_for_product(product_id):
        """Get all sellers offering a specific product"""
        rows = app.db.execute('''
            SELECT i.inventory_id, i.seller_id, i.product_id, i.quantity, i.unit_price, 
                   i.created_at, i.updated_at, i.owner_id, p.product_name, CONCAT(a.first_name, ' ', a.last_name) AS seller_name,
                   p.category_id, pc.category_name, p.image
            FROM Inventory i
            JOIN Products p ON i.product_id = p.product_id
            JOIN Accounts a ON i.seller_id = a.user_id
            JOIN Products_Categories pc ON p.category_id = pc.category_id
            WHERE i.product_id = :product_id AND i.quantity > 0
            ORDER BY i.unit_price
        ''', product_id=product_id)

        return [Inventory(*row) for row in rows]

    @staticmethod
    def update_quantity(seller_id, product_id, quantity_change):
        """Update inventory quantity (used for order processing)"""
        try:
            # First get current quantity to check if we have enough
            current = app.db.execute('''
                SELECT quantity FROM Inventory 
                WHERE seller_id = :seller_id AND product_id = :product_id
                FOR UPDATE
            ''', seller_id=seller_id, product_id=product_id)

            if not current:
                return False

            current_quantity = current[0][0]
            new_quantity = current_quantity + quantity_change

            if new_quantity < 0:
                return False

            app.db.execute('''
                UPDATE Inventory 
                SET quantity = :new_quantity, updated_at = :updated_at
                WHERE seller_id = :seller_id AND product_id = :product_id
            ''', new_quantity=new_quantity, updated_at=datetime.utcnow(),
                           seller_id=seller_id, product_id=product_id)

            return True
        except Exception as e:
            print(f"Error updating inventory quantity: {e}")
            return False