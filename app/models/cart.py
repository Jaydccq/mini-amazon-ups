# app/models/cart.py
from flask import current_app as app
from datetime import datetime
from app.model import db, Cart, CartProduct, Order, OrderProduct, Product, User, Warehouse

class CartService:
    @staticmethod
    def add_to_cart(user_id, product_id, seller_id, quantity):
        """Add a product to the user's cart"""
        try:
            # Check if cart exists, create if not
            cart = Cart.query.filter_by(user_id=user_id).first()
            if not cart:
                cart = Cart(user_id=user_id)
                db.session.add(cart)
                db.session.flush()
            
            # Get product price
            product = Product.query.filter_by(product_id=product_id).first()
            if not product:
                return False, "Product not found"
            
            # Check if item already in cart
            cart_item = CartProduct.query.filter_by(
                cart_id=cart.cart_id,
                product_id=product_id,
                seller_id=seller_id
            ).first()
            
            if cart_item:
                cart_item.quantity += quantity
                cart_item.updated_at = datetime.utcnow()
            else:
                cart_item = CartProduct(
                    cart_id=cart.cart_id,
                    product_id=product_id,
                    seller_id=seller_id,
                    quantity=quantity,
                    price_at_addition=product.price
                )
                db.session.add(cart_item)
            
            db.session.commit()
            return True, cart.cart_id
        except Exception as e:
            db.session.rollback()
            return False, str(e)
    
    @staticmethod
    def checkout_cart(user_id):
        """Process cart checkout and create orders/shipments"""
        try:
            # Begin transaction
            db.session.begin()
            
            # Get user's cart
            cart = Cart.query.filter_by(user_id=user_id).first()
            if not cart or not cart.items:
                db.session.rollback()
                return False, "Cart is empty"
            
            # Calculate total
            total_amount = sum(item.quantity * item.price_at_addition for item in cart.items)
            
            # Create order
            order = Order(
                buyer_id=user_id,
                total_amount=total_amount,
                num_products=sum(item.quantity for item in cart.items),
                order_status='Unfulfilled'
            )
            db.session.add(order)
            db.session.flush()
            
            # Create order items
            for cart_item in cart.items:
                order_item = OrderProduct(
                    order_id=order.order_id,
                    product_id=cart_item.product_id,
                    quantity=cart_item.quantity,
                    price=cart_item.price_at_addition,
                    seller_id=cart_item.seller_id,
                    status='Unfulfilled'
                )
                db.session.add(order_item)
            
            # Create shipment
            from app.services.shipment_service import ShipmentService
            shipment_service = ShipmentService()
            
            # Find nearest warehouse
            from app.services.warehouse_service import WarehouseService
            warehouse_service = WarehouseService()
            warehouse = warehouse_service.get_nearest_warehouse(0, 0)  # Default coordinates
            
            if not warehouse:
                db.session.rollback()
                return False, "No warehouse available"
            
            # Create shipment
            shipment_success, shipment_result = shipment_service.create_shipment(
                order_id=order.order_id,
                warehouse_id=warehouse.warehouse_id,
                destination_x=0,  # Default coordinates
                destination_y=0,   # Default coordinates
                ups_account=None   # Optional
            )
            
            if not shipment_success:
                db.session.rollback()
                return False, shipment_result
            
            # Clear cart
            for item in cart.items:
                db.session.delete(item)
            
            db.session.commit()
            return True, order.order_id
        except Exception as e:
            db.session.rollback()
            return False, str(e)
    
    @staticmethod
    def get_cart_items(user_id):
        try:
            cart = Cart.query.filter_by(user_id=user_id).first()
            if not cart:
                return []
            
            items = []
            for item in cart.items:
                product = Product.query.filter_by(product_id=item.product_id).first()
                seller = User.query.filter_by(user_id=item.seller_id).first()
                
                if product and seller:
                    items.append({
                        'product_id': product.product_id,
                        'product_name': product.product_name,
                        'description': product.description,
                        'image': product.image,
                        'seller_id': seller.user_id,
                        'seller_name': f"{seller.first_name} {seller.last_name}",
                        'quantity': item.quantity,
                        'unit_price': float(item.price_at_addition),
                        'total_price': float(item.quantity * item.price_at_addition)
                    })
            
            return items
        except Exception as e:
            return []