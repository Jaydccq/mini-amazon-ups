from sqlalchemy import text
from app.model import db             
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
        # CORRECTED: Use db.session
        rows = db.session.execute(
            text('''
                SELECT i.inventory_id, i.seller_id, i.product_id, i.quantity, i.unit_price,
                       i.created_at, i.updated_at, i.owner_id, p.product_name, CONCAT(a.first_name, ' ', a.last_name) AS seller_name,
                       p.category_id, pc.category_name, p.image
                FROM Inventory i
                JOIN Products p ON i.product_id = p.product_id
                JOIN Accounts a ON i.seller_id = a.user_id
                JOIN Products_Categories pc ON p.category_id = pc.category_id
                WHERE i.inventory_id = :inventory_id
            '''),
            {"inventory_id": inventory_id}
        ).fetchall()

        return Inventory(*rows[0]) if rows else None

    @staticmethod
    def get_by_seller_and_product(seller_id, product_id):
        rows = db.session.execute(
            text('''
                SELECT i.inventory_id, i.seller_id, i.product_id, i.quantity, i.unit_price,
                       i.created_at, i.updated_at, p.product_name, CONCAT(a.first_name, ' ', a.last_name) AS seller_name,
                       p.category_id, pc.category_name, p.image
                FROM Inventory i
                JOIN Products p ON i.product_id = p.product_id
                JOIN Accounts a ON i.seller_id = a.user_id
                JOIN Products_Categories pc ON p.category_id = pc.category_id
                WHERE i.seller_id = :seller_id AND i.product_id = :product_id
            '''),
            {"seller_id": seller_id, "product_id": product_id}
        ).fetchall()

        # Assuming the Inventory class __init__ matches the columns selected
        return Inventory(*rows[0]) if rows else None

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

        rows = db.session.execute(text(query), params).fetchall()
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

        result = db.session.execute(text(query), params).fetchall()
        return result[0][0] if result else 0

    @staticmethod
    def create(seller_id, product_id, quantity, unit_price):
        try:
            owner_rows = db.session.execute(
                text('''
                    SELECT owner_id FROM Products WHERE product_id = :product_id
                '''),
                {"product_id": product_id}
            ).fetchall()

            if not owner_rows:
                 print(f"Error: Product with ID {product_id} not found to get owner_id.")
                 return None # Product must exist

            owner_id = owner_rows[0][0]

            inventory_id_result = db.session.execute(
                text('''
                    INSERT INTO Inventory (seller_id, product_id, quantity, unit_price, owner_id)
                    VALUES (:seller_id, :product_id, :quantity, :unit_price, :owner_id)
                    RETURNING inventory_id
                '''),
                {
                    "seller_id": seller_id,
                    "product_id": product_id,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "owner_id": owner_id 
                }
            ).fetchone() 

            return inventory_id_result[0] if inventory_id_result else None
        except Exception as e:

            print(f"Error creating inventory: {e}")
            return None

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
        try:
            update_parts = []
            params = {'inventory_id': inventory_id, 'seller_id': seller_id}

            if quantity is None and unit_price is None:
                 print("Warning: Inventory.update called without quantity or unit_price.")
                 return None 

            if quantity is not None:
                if not isinstance(quantity, int) or quantity < 0:
                     print(f"Error: Invalid quantity '{quantity}' for Inventory update.")
                     return None # Invalid quantity
                update_parts.append("quantity = :quantity")
                params['quantity'] = quantity

            if unit_price is not None:
                 try:
                     price_val = float(unit_price)
                     if price_val < 0: raise ValueError("Price cannot be negative")
                     update_parts.append("unit_price = :unit_price")
                     params['unit_price'] = price_val
                 except (ValueError, TypeError) as price_err:
                      print(f"Error: Invalid unit_price '{unit_price}' for Inventory update: {price_err}")
                      return None

            if update_parts:
                update_parts.append("updated_at = :updated_at")
                params['updated_at'] = datetime.utcnow()

                query = f'''
                    UPDATE Inventory
                    SET {", ".join(update_parts)}
                    WHERE inventory_id = :inventory_id AND seller_id = :seller_id
                    RETURNING inventory_id
                '''
                result = db.session.execute(text(query), params).fetchone() 

                return result[0] if result else None
            else:
                 return None

        except Exception as e:
            print(f"Error updating inventory {inventory_id} for seller {seller_id}: {e}")
            return None

    @staticmethod
    def delete(inventory_id, seller_id):
        try:
            result = db.session.execute(
                text('''
                    DELETE FROM Inventory
                    WHERE inventory_id = :inventory_id AND seller_id = :seller_id
                    RETURNING inventory_id
                '''),
                {"inventory_id": inventory_id, "seller_id": seller_id}
            ).fetchone() # Use fetchone()


            return result[0] if result else None
        except Exception as e:
       
            print(f"Error deleting inventory {inventory_id} for seller {seller_id}: {e}")
            return None

    @staticmethod
    def get_sellers_for_product(product_id):
        try: # Added try-except block
            
            rows = db.session.execute(
                text('''
                    SELECT i.inventory_id, i.seller_id, i.product_id, i.quantity, i.unit_price,
                           i.created_at, i.updated_at, i.owner_id, p.product_name, CONCAT(a.first_name, ' ', a.last_name) AS seller_name,
                           p.category_id, pc.category_name, p.image
                    FROM Inventory i
                    JOIN Products p ON i.product_id = p.product_id
                    JOIN Accounts a ON i.seller_id = a.user_id
                    JOIN Products_Categories pc ON p.category_id = pc.category_id
                    WHERE i.product_id = :product_id AND i.quantity > 0
                    ORDER BY i.unit_price
                '''),
                {"product_id": product_id}
            ).fetchall()

            return [Inventory(*row) for row in rows]
        except Exception as e:
             print(f"Error in get_sellers_for_product for product {product_id}: {e}")
             return [] 

    @staticmethod
    def update_quantity(seller_id, product_id, quantity_change):
        try:
            current = db.session.execute(
                text('''
                    SELECT quantity FROM Inventory
                    WHERE seller_id = :seller_id AND product_id = :product_id
                    FOR UPDATE
                '''),
                {"seller_id": seller_id, "product_id": product_id}
            ).fetchone() # Use fetchone()

            if not current:
                print(f"Warning: Inventory record not found for seller {seller_id}, product {product_id} during update_quantity.")
                return False # Inventory record doesn't exist

            current_quantity = current[0]
            new_quantity = current_quantity + quantity_change

            if new_quantity < 0:
                print(f"Error: Insufficient stock for seller {seller_id}, product {product_id}. Required change: {quantity_change}, Available: {current_quantity}")
                return False # Not enough stock

            # CORRECTED: Use db.session
            db.session.execute(
                text('''
                    UPDATE Inventory
                    SET quantity = :new_quantity, updated_at = :updated_at
                    WHERE seller_id = :seller_id AND product_id = :product_id
                '''),
                {
                    "new_quantity": new_quantity,
                    "updated_at": datetime.utcnow(),
                    "seller_id": seller_id,
                    "product_id": product_id
                }
            )
            return True
        except Exception as e:
            print(f"Error updating inventory quantity for seller {seller_id}, product {product_id}: {e}")
            return False

    @staticmethod
    def get_warehouse_id_by_productId_sellerId(product_id, seller_id):
        try:
            rows = db.session.execute(
                text('''
                    SELECT inventory_id
                    FROM Inventory
                    WHERE product_id = :product_id AND owner_id = :owner_id
                '''),
                {"product_id": product_id, "seller_id": seller_id}
            ).first()

            return rows[0][0] if rows else None
        except Exception as e:
            print(f"Error getting warehouse ID for product {product_id} and seller {seller_id}: {e}")
            return None