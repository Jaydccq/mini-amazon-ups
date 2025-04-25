from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from flask import current_app
import logging

db = SQLAlchemy()
logger = logging.getLogger(__name__)


class User(UserMixin, db.Model):
    __tablename__ = 'accounts'
    
    user_id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    address = db.Column(db.Text, nullable=True)
    password = db.Column(db.String(255), nullable=False)
    current_balance = db.Column(db.Numeric(10, 2), default=0.00)
    is_seller = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    orders = db.relationship('Order', back_populates='user', foreign_keys='Order.buyer_id')
    cart = db.relationship('Cart', uselist=False, back_populates='user')


    
    def set_password(self, password):
        self.password = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password, password)
    
    def get_id(self):
        return str(self.user_id)

class ProductCategory(db.Model):
    __tablename__ = 'products_categories'
    
    category_id = db.Column(db.Integer, primary_key=True)
    category_name = db.Column(db.String(100), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    products = db.relationship('Product', back_populates='category')

class Product(db.Model):
    __tablename__ = 'products'
    
    product_id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('products_categories.category_id'), nullable=False)
    product_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    image = db.Column(db.String(255))
    price = db.Column(db.Numeric(10, 2), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('accounts.user_id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    category = db.relationship('ProductCategory', back_populates='products')
    owner = db.relationship('User')
    inventory_items = db.relationship('WarehouseProduct', back_populates='product')
    shipment_items = db.relationship('ShipmentItem', back_populates='product')
    cart_items = db.relationship('CartProduct', back_populates='product')
    order_items = db.relationship('OrderProduct', back_populates='product')

class Cart(db.Model):
    __tablename__ = 'carts'
    
    cart_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('accounts.user_id'), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', back_populates='cart')
    items = db.relationship('CartProduct', back_populates='cart', cascade='all, delete-orphan')
    
    @classmethod
    def checkout_cart(cls, user_id,destination_x,destination_y,ups_account):
        """Process cart checkout and create an order"""
        logger.info(f"Begin Checkout cart")
        from app.services.shipment_service import ShipmentService
        shipment_service = ShipmentService(current_app.config.get('WORLD_SIMULATOR_SERVICE'))
        try:
            # Get the user's cart
            logger.info(f"Checking out cart for user {user_id}")
            cart = Cart.query.filter_by(user_id=user_id).first()
            if not cart or not cart.items:
                return False, -1

            checkout_count = 0
            # Create orders
            for cart_item in cart.items:
                logger.info(f"Processing cart item {cart_item.product_id} for user {user_id}")
                # Create new order
                order = Order(
                    buyer_id=user_id,
                    total_amount=cart_item.quantity * cart_item.price_at_addition,
                    num_products=cart_item.quantity,
                    order_status='Unfulfilled'
                )
                db.session.add(order)
                db.session.flush()  # Get the order ID

                logger.info("getting warehouse id")

                warehouse_id = Inventory.get_warehouse_id_by_productId_sellerId(cart_item.product_id,
                                                                                cart_item.seller_id)

                order_item = OrderProduct(
                    order_id=order.order_id,
                    product_id=cart_item.product_id,
                    quantity=cart_item.quantity,
                    price=cart_item.price_at_addition,
                    seller_id=cart_item.seller_id,
                    status='Unfulfilled'
                )
                db.session.add(order_item)

                db.session.delete(cart_item)

                # subtract from inventory

                logger.info("subtracting from inventory")
                inventory_item = WarehouseProduct.query.filter_by(
                    warehouse_id=warehouse_id,
                    product_id=cart_item.product_id
                ).first()

                if inventory_item:
                    inventory_item.quantity -= cart_item.quantity
                    if inventory_item.quantity < 0:
                        db.session.rollback()
                        return False, checkout_count
                    
                logger.info(f"Send Request of creating shipment for product {cart_item.product_id} in warehouse {warehouse_id}")

                shipment_success, shipment_id_or_error = shipment_service.create_shipment(
                    order_id=order.order_id,
                    warehouse_id=warehouse_id,
                    destination_x=destination_x,
                    destination_y=destination_y,
                    ups_account=ups_account
                )

                logger.info(f"Shipment creation result: {shipment_success}, ID/Error: {shipment_id_or_error}")

                if not shipment_success:
                    db.session.rollback()
                    return False, checkout_count

                db.session.commit()
                checkout_count+=1

            return True, checkout_count
        except Exception as e:
            db.session.rollback()
            return False, -1

class CartProduct(db.Model):
    __tablename__ = 'cart_products'
    
    cart_id = db.Column(db.Integer, db.ForeignKey('carts.cart_id'), primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.product_id'), primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('accounts.user_id'), primary_key=True)
    quantity = db.Column(db.Integer, default=1, nullable=False)
    price_at_addition = db.Column(db.Numeric(10, 2), nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    cart = db.relationship('Cart', back_populates='items')
    product = db.relationship('Product', back_populates='cart_items')
    seller = db.relationship('User')

class Order(db.Model):
    __tablename__ = 'orders'
    
    order_id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('accounts.user_id'), nullable=False)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    order_date = db.Column(db.DateTime, default=datetime.utcnow)
    num_products = db.Column(db.Integer, nullable=False)
    order_status = db.Column(db.String(20), nullable=False, default='Unfulfilled')
    
    # Relationships
    user = db.relationship('User', foreign_keys=[buyer_id], back_populates='orders')
    items = db.relationship('OrderProduct', back_populates='order', cascade='all, delete-orphan')
    shipments = db.relationship('Shipment', back_populates='order', cascade='all, delete-orphan')
    
    __table_args__ = (
        db.CheckConstraint(
            "order_status IN ('Unfulfilled', 'Fulfilled')",
            name='orders_order_status_check'
        ),
    )

class OrderProduct(db.Model):
    __tablename__ = 'orders_products'
    
    order_item_id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.order_id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.product_id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey('accounts.user_id'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='Unfulfilled')
    fulfillment_date = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    order = db.relationship('Order', back_populates='items')
    product = db.relationship('Product', back_populates='order_items')
    seller = db.relationship('User')
    
    __table_args__ = (
        db.UniqueConstraint('order_id', 'product_id', 'seller_id', name='uc_order_product_seller'),
        db.CheckConstraint(
            "status IN ('Unfulfilled', 'Fulfilled')",
            name='orders_products_status_check'
        ),
    )

# World Simulator and UPS integration models
class Warehouse(db.Model):


    __tablename__ = 'warehouses'
    
    warehouse_id = db.Column(db.Integer, primary_key=True)
    x = db.Column(db.Integer, nullable=False)  # X coordinate in the world
    y = db.Column(db.Integer, nullable=False)  # Y coordinate in the world
    world_id = db.Column(db.BigInteger, nullable=True)  # World ID for identification
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    products = db.relationship('WarehouseProduct', back_populates='warehouse', cascade='all, delete-orphan', lazy='dynamic')
    shipments = db.relationship('Shipment', back_populates='warehouse')

class WarehouseProduct(db.Model):
    __tablename__ = 'warehouse_products'
    
    id = db.Column(db.Integer, primary_key=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.warehouse_id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.product_id'), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    warehouse = db.relationship('Warehouse', back_populates='products')
    product = db.relationship('Product', back_populates='inventory_items')
    
    __table_args__ = (
        db.UniqueConstraint('warehouse_id', 'product_id', name='uc_warehouse_product'),
    )

class Shipment(db.Model):
    __tablename__ = 'shipments'
    
    shipment_id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.order_id'), nullable=False)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.warehouse_id'), nullable=False)
    truck_id = db.Column(db.BigInteger, nullable=True)  # ID of the UPS truck assigned
    ups_tracking_id = db.Column(db.String(255), nullable=True)  # UPS tracking number
    ups_account = db.Column(db.String(255), nullable=True)  # Associated UPS account (if specified)
    destination_x = db.Column(db.Integer, nullable=False)  # Destination X coordinate
    destination_y = db.Column(db.Integer, nullable=False)  # Destination Y coordinate
    status = db.Column(db.String(50), nullable=False, default='packing')  # packing, packed, loading, loaded, delivering, delivered
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    order = db.relationship('Order', back_populates='shipments')
    warehouse = db.relationship('Warehouse', back_populates='shipments')
    items = db.relationship('ShipmentItem', back_populates='shipment', cascade='all, delete-orphan')
    
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('packing', 'packed', 'loading', 'loaded', 'delivering', 'delivered')",
            name='shipments_status_check'
        ),
    )

class ShipmentItem(db.Model):
    __tablename__ = 'shipment_items'
    
    item_id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey('shipments.shipment_id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.product_id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    shipment = db.relationship('Shipment', back_populates='items')
    product = db.relationship('Product', back_populates='shipment_items')
    
    __table_args__ = (
        db.UniqueConstraint('shipment_id', 'product_id', name='uc_shipment_product'),
    )

class WorldMessage(db.Model):
    __tablename__ = 'world_messages'

    id = db.Column(db.Integer, primary_key=True)
    seqnum = db.Column(db.BigInteger, nullable=False)
    message_type = db.Column(db.String(50), nullable=False)  # e.g., buy, topack, load
    message_content = db.Column(db.Text, nullable=False)  # Store relevant details
    status = db.Column(db.String(20), nullable=False, default='sent')  # sent, acked, failed
    retries = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('sent', 'acked', 'failed')",
            name='world_messages_status_check'
        ),
    )

    def __repr__(self):
        return f'<WorldMessage {self.id} Seq:{self.seqnum} Type:{self.message_type} Status:{self.status}>'


class UPSMessage(db.Model):
    __tablename__ = 'ups_messages'
    
    id = db.Column(db.Integer, primary_key=True)
    message_type = db.Column(db.String(50), nullable=False)  # package_created, package_packed, package_loaded, etc.
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    payload = db.Column(db.Text, nullable=False)  # JSON

# app/model.py
# ... (all other existing model classes like User, Product, Order, Shipment, etc.) ...

class Review(db.Model):
    __tablename__ = 'reviews'

    review_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('accounts.user_id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.product_id'), nullable=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('accounts.user_id'), nullable=True)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=True)
    review_date = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id])
    product = db.relationship('Product', foreign_keys=[product_id])
    seller = db.relationship('User', foreign_keys=[seller_id])

    __table_args__ = (
        db.CheckConstraint(
            '(product_id IS NOT NULL AND seller_id IS NULL) OR (product_id IS NULL AND seller_id IS NOT NULL)',
            name='review_target_check'
        ),
        db.CheckConstraint('rating >= 1 AND rating <= 5', name='review_rating_check'),
    )

class Inventory(db.Model):
    __tablename__ = 'inventory' 

    inventory_id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('accounts.user_id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.product_id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # owner_id might be redundant if product.owner_id is always the same,
    # but keeping it if your SQL defines it. Check if needed.
    owner_id = db.Column(db.Integer, db.ForeignKey('accounts.user_id'), nullable=True)

    # Relationships
    seller = db.relationship('User', foreign_keys=[seller_id])
    product = db.relationship('Product') # Add backref in Product model if needed
    product_owner = db.relationship('User', foreign_keys=[owner_id])

    __table_args__ = (
        db.UniqueConstraint('seller_id', 'product_id', name='uq_inventory_seller_product'),
    )