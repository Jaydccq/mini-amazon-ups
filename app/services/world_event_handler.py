import threading
import logging
from app.services.warehouse_service import WarehouseService
from app.services.shipment_service import ShipmentService
from flask import current_app
from datetime import datetime, timezone
from app import db
logger = logging.getLogger(__name__)

class WorldEventHandler:
    def __init__(self,app=None):
        self.app = app
        self.warehouse_service = WarehouseService()
        self.shipment_service = ShipmentService(world_simulator_service=current_app.config.get('WORLD_SIMULATOR_SERVICE'))

    # Handle world events    
    def handle_world_event(self, event_type, event_data):

        with current_app.app_context():
            try:
                if event_type == 'product_arrived':
                    return self.handle_product_arrived(event_data)
                elif event_type == 'package_ready':
                    return self.handle_package_ready(event_data)
                elif event_type == 'package_loaded':
                    return self.handle_package_loaded(event_data)
                else:
                    logger.warning(f"Unknown event type: {event_type}")
                    return False, f"Unknown event type: {event_type}"
            except Exception as e:
                logger.error(f"Error handling world event: {str(e)}")
                return False, str(e)
    
    # when a product arrives at the warehouse
    def handle_product_arrived(self, event_data):
        warehouse_id = event_data.get('warehouse_id')
        product_id = event_data.get('product_id')
        description = event_data.get('description')
        quantity = event_data.get('quantity')
        
        if not all([warehouse_id, product_id, description, quantity]):
            return False, "Missing required fields"
        
        return self.warehouse_service.handle_product_arrived(
            warehouse_id=warehouse_id,
            product_id=product_id,
            description=description,
            quantity=quantity
        )
    

    def handle_package_ready(self, event_data):
        shipment_id = event_data.get('shipment_id')
        waiting_products = current_app.config.get('WAITING_PRODUCTS', {})
        if shipment_id not in waiting_products:
            return self.shipment_service.handle_package_packed(shipment_id)
        else:
            warehouse_id = event_data.get('warehouse_id')
            logger.info(f"Processing package ready event: {event_data}")
            logger.info(f"Shipment {shipment_id} is waiting for products: {waiting_products}")
            truck_id = waiting_products[shipment_id]
            try:
                shipment = self.shipment_service.get_shipment_by_id(shipment_id)
                if shipment:
                    shipment.status = 'loading'
                    shipment.truck_id = truck_id
                    shipment.updated_at = datetime.now(timezone.utc)
                    db.session.commit()
                    logger.info(f"Updated shipment {shipment_id} status to 'loading'")
                else:
                    logger.warning(f"Shipment {shipment_id} not found in database")
                    if shipment:
                        shipment.status = 'loading'
                        shipment.truck_id = truck_id
                        shipment.updated_at = datetime.now(timezone.utc)
                        db.session.commit()
                        logger.info(f"Updated shipment {shipment_id} status to 'loading'")
                    else:
                        logger.warning(f"Shipment {shipment_id} not found in database")
            except Exception as e:
                logger.error(f"Error updating shipment status: {e}")
                db.session.rollback()

            # Use the world simulator service from the shipment_service
            self.shipment_service.world_simulator_service.load_shipment(
                    shipment_id=shipment_id,
                    truck_id=waiting_products[shipment_id],
                    warehouse_id=warehouse_id
                )
            del waiting_products[shipment_id]
            current_app.config['WAITING_PRODUCTS'] = waiting_products
            return True, f"Shipment {shipment_id} is being loaded onto truck {waiting_products[shipment_id]} at warehouse {warehouse_id}"

    
    def handle_package_loaded(self, event_data):
        shipment_id = event_data.get('shipment_id')
        truck_id = event_data.get('truck_id')
        
        if not all([shipment_id, truck_id]):
            return False, "Missing required fields"
        
        # Use shipment service to handle the package being loaded
        return self.shipment_service.handle_package_loaded(shipment_id, truck_id)