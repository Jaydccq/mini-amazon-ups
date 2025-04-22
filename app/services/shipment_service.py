from datetime import datetime
import logging
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError
from app.model import db, Shipment, ShipmentItem, Order, OrderProduct, Product, Warehouse
from app.services.world_simulator_service import WorldSimulatorService
from app.services.ups_integration_service import UPSIntegrationService

logger = logging.getLogger(__name__)

class ShipmentService:
    def __init__(self):
        self.world_simulator = WorldSimulatorService()
        self.ups_integration = UPSIntegrationService()
    
    def create_shipment(self, order_id, warehouse_id, destination_x, destination_y, ups_account=None):
        """Create a new shipment for an order"""
        try:
            # Get the order
            order = Order.query.filter_by(order_id=order_id).first()
            if not order:
                return False, "Order not found"
            
            # Check if the warehouse exists
            warehouse = Warehouse.query.filter_by(warehouse_id=warehouse_id).first()
            if not warehouse:
                return False, "Warehouse not found"
            
            # Check if a shipment already exists for this order
            existing_shipment = Shipment.query.filter_by(order_id=order_id).first()
            if existing_shipment:
                return False, "A shipment already exists for this order"
            
            # Create the shipment
            shipment = Shipment(
                order_id=order_id,
                warehouse_id=warehouse_id,
                destination_x=destination_x,
                destination_y=destination_y,
                ups_account=ups_account,
                status='packing'
            )
            db.session.add(shipment)
            db.session.flush()  # Get the shipment ID without committing yet
            
            # Get order items
            order_items = OrderProduct.query.filter_by(order_id=order_id).all()
            if not order_items:
                return False, "Order has no items"
            
            # Create shipment items
            for order_item in order_items:
                shipment_item = ShipmentItem(
                    shipment_id=shipment.shipment_id,
                    product_id=order_item.product_id,
                    quantity=order_item.quantity
                )
                db.session.add(shipment_item)
            
            # Commit to database
            db.session.commit()
            
            # Notify UPS about the package
            self.ups_integration.notify_package_created(
                shipment_id=shipment.shipment_id,
                destination_x=destination_x,
                destination_y=destination_y,
                ups_account=ups_account
            )
            
            # Request packing from world simulator
            items = []
            for order_item in order_items:
                product = Product.query.filter_by(product_id=order_item.product_id).first()
                if product:
                    items.append({
                        'product_id': order_item.product_id,
                        'description': product.product_name,
                        'quantity': order_item.quantity
                    })
            
            if items:
                self.world_simulator.pack_shipment(
                    warehouse_id=warehouse_id,
                    shipment_id=shipment.shipment_id,
                    items=items
                )
            
            return True, shipment.shipment_id
        
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Database error creating shipment: {str(e)}")
            return False, f"Database error: {str(e)}"
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating shipment: {str(e)}")
            return False, f"Error: {str(e)}"
    
    def get_shipment(self, shipment_id):
        """Get a shipment by ID"""
        return Shipment.query.filter_by(shipment_id=shipment_id).first()
    
    def get_shipments_for_order(self, order_id):
        """Get all shipments for an order"""
        return Shipment.query.filter_by(order_id=order_id).all()
    
    def handle_package_packed(self, shipment_id):
        """Handle notification that a package has been packed by the warehouse"""
        try:
            shipment = Shipment.query.filter_by(shipment_id=shipment_id).first()
            if not shipment:
                return False, "Shipment not found"
            
            # Update shipment status
            shipment.status = 'packed'
            shipment.updated_at = datetime.utcnow()
            db.session.commit()
            
            # Notify UPS that the package is packed and ready for pickup
            self.ups_integration.notify_package_packed(shipment_id)
            
            return True, "Shipment marked as packed"
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error handling package packed: {str(e)}")
            return False, str(e)
    
    def handle_truck_arrived(self, truck_id, warehouse_id):
        """Handle notification that a truck has arrived at the warehouse"""
        try:
            # Find all shipments at this warehouse that are packed
            shipments = Shipment.query.filter_by(
                warehouse_id=warehouse_id,
                status='packed'
            ).all()
            
            if not shipments:
                logger.info(f"No packed shipments found at warehouse {warehouse_id} for truck {truck_id}")
                return True
            
            # Update shipments and request loading
            for shipment in shipments:
                shipment.truck_id = truck_id
                shipment.status = 'loading'
                shipment.updated_at = datetime.utcnow()
                
                # Request loading from world simulator
                self.world_simulator.load_shipment(
                    shipment_id=shipment.shipment_id,
                    truck_id=truck_id,
                    warehouse_id=warehouse_id
                )
            
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error handling truck arrival: {str(e)}")
            return False
    
    def handle_package_loaded(self, shipment_id, truck_id):
        """Handle notification that a package has been loaded onto a truck"""
        try:
            shipment = Shipment.query.filter_by(shipment_id=shipment_id).first()
            if not shipment:
                return False, "Shipment not found"
            
            # Update shipment status
            shipment.status = 'loaded'
            shipment.updated_at = datetime.utcnow()
            db.session.commit()
            
            # Notify UPS that the package is loaded
            self.ups_integration.notify_package_loaded(shipment_id, truck_id)
            
            return True, "Shipment marked as loaded"
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error handling package loaded: {str(e)}")
            return False, str(e)
    
    def handle_package_delivered(self, shipment_id):
        """Handle notification that a package has been delivered"""
        try:
            shipment = Shipment.query.filter_by(shipment_id=shipment_id).first()
            if not shipment:
                return False, "Shipment not found"
            
            # Update shipment status
            shipment.status = 'delivered'
            shipment.updated_at = datetime.utcnow()
            
            # Check if all shipments for the order are delivered
            all_shipments = Shipment.query.filter_by(order_id=shipment.order_id).all()
            all_delivered = all(s.status == 'delivered' for s in all_shipments)
            
            # If all shipments are delivered, mark the order as fulfilled
            if all_delivered:
                order = Order.query.filter_by(order_id=shipment.order_id).first()
                if order:
                    order.order_status = 'Fulfilled'
                    
                    # Update order items
                    order_items = OrderProduct.query.filter_by(order_id=order.order_id).all()
                    for item in order_items:
                        item.status = 'Fulfilled'
                        item.fulfillment_date = datetime.utcnow()
            
            db.session.commit()
            return True, "Package delivery processed successfully"
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error handling package delivery: {str(e)}")
            return False, str(e)
    
    def get_shipment_status(self, shipment_id):
        """Get detailed shipment status including items"""
        try:
            shipment = Shipment.query.filter_by(shipment_id=shipment_id).first()
            if not shipment:
                return None
            
            # Get warehouse info
            warehouse = Warehouse.query.filter_by(warehouse_id=shipment.warehouse_id).first()
            
            # Get order info
            order = Order.query.filter_by(order_id=shipment.order_id).first()
            
            # Get shipment items
            items = []
            shipment_items = ShipmentItem.query.filter_by(shipment_id=shipment_id).all()
            for item in shipment_items:
                product = Product.query.filter_by(product_id=item.product_id).first()
                items.append({
                    'product_id': item.product_id,
                    'product_name': product.product_name if product else 'Unknown Product',
                    'quantity': item.quantity
                })
            
            # Build comprehensive status
            status_data = {
                'shipment_id': shipment.shipment_id,
                'order_id': shipment.order_id,
                'status': shipment.status,
                'warehouse': {
                    'id': warehouse.warehouse_id,
                    'x': warehouse.x,
                    'y': warehouse.y
                } if warehouse else None,
                'destination': {
                    'x': shipment.destination_x,
                    'y': shipment.destination_y
                },
                'ups_tracking_id': shipment.ups_tracking_id,
                'ups_account': shipment.ups_account,
                'truck_id': shipment.truck_id,
                'created_at': shipment.created_at.isoformat() if shipment.created_at else None,
                'updated_at': shipment.updated_at.isoformat() if shipment.updated_at else None,
                'items': items,
                'total_amount': float(order.total_amount) if order else 0
            }
            
            return status_data
        except Exception as e:
            logger.error(f"Error getting shipment status: {str(e)}")
            return None