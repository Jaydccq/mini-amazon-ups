import threading
import logging
from app.services.warehouse_service import WarehouseService
from app.services.shipment_service import ShipmentService
from flask import current_app

logger = logging.getLogger(__name__)

class WorldEventHandler:
    def __init__(self,app=None):
        self.app = app
        self.warehouse_service = WarehouseService()
        self.shipment_service = ShipmentService()

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
        
        if not shipment_id:
            return False, "Missing shipment_id"
        
        # Use shipment service to handle the package being ready
        return self.shipment_service.handle_package_packed(shipment_id)
    
    def handle_package_loaded(self, event_data):
        shipment_id = event_data.get('shipment_id')
        truck_id = event_data.get('truck_id')
        
        if not all([shipment_id, truck_id]):
            return False, "Missing required fields"
        
        # Use shipment service to handle the package being loaded
        return self.shipment_service.handle_package_loaded(shipment_id, truck_id)