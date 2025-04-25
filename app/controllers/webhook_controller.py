# app/controllers/webhook_controller.py

from flask import Blueprint, request, jsonify, current_app
# Import the service classes
from app.services.world_event_handler import WorldEventHandler 
from app.services.ups_integration_service import UPSIntegrationService 
from app.services.shipment_service import ShipmentService 

# Create the blueprints
world_bp = Blueprint('world', __name__, url_prefix='/api/world')
ups_bp = Blueprint('ups', __name__, url_prefix='/api/ups')

# !! REMOVE global instantiations !!
# world_event_handler = WorldEventHandler() # REMOVED
# ups_integration = UPSIntegrationService() # REMOVED
# shipment_service = ShipmentService() # REMOVED

@world_bp.route('/event', methods=['POST'])
def handle_world_event():
    # Instantiate handler INSIDE the route
    world_event_handler = WorldEventHandler() 
    
    data = request.json
    if not data or 'event_type' not in data or 'event_data' not in data:
        return jsonify({
            'success': False,
            'error': 'Missing required fields'
        }), 400
    
    event_type = data['event_type']
    event_data = data['event_data']
    
    acks = []
    if 'seqnum' in data:
        acks.append(data['seqnum'])
    
    # Use the locally instantiated handler
    success, message = world_event_handler.handle_world_event(event_type, event_data) 
    
    return jsonify({
        'success': success,
        'message': message,
        'acks': acks
    })

@ups_bp.route('/truck-arrived', methods=['POST'])
def handle_truck_arrived():
    # Instantiate service INSIDE the route
    shipment_service = ShipmentService() 
    
    data = request.json
    if not data or 'truck_id' not in data or 'warehouse_id' not in data:
        return jsonify({
            'success': False,
            'error': 'Missing required fields'
        }), 400
    
    acks = []
    if 'seqnum' in data:
        acks.append(data['seqnum'])
    
    # Use the locally instantiated service
    success = shipment_service.handle_truck_arrived(data['truck_id'], data['warehouse_id']) 
    
    return jsonify({
        'success': success,
        'acks': acks
    })

@ups_bp.route('/package-delivered', methods=['POST'])
def handle_package_delivered():
    # Instantiate service INSIDE the route
    shipment_service = ShipmentService() 
    
    data = request.json
    if not data or 'shipment_id' not in data:
        return jsonify({
            'success': False,
            'error': 'Missing required fields'
        }), 400
    
    acks = []
    if 'seqnum' in data:
        acks.append(data['seqnum'])
    
    # Use the locally instantiated service
    success, message = shipment_service.handle_package_delivered(data['shipment_id']) 
    
    return jsonify({
        'success': success,
        'message': message,
        'acks': acks
    })

@ups_bp.route('/tracking', methods=['POST'])
def add_tracking_number():
    # No service needed here directly, just DB access
    data = request.json
    if not data or 'shipment_id' not in data or 'tracking_id' not in data:
        return jsonify({
            'success': False,
            'error': 'Missing required fields'
        }), 400
    
    acks = []
    if 'seqnum' in data:
        acks.append(data['seqnum'])
    
    try:
        # Import model here, inside the function
        from app.model import db, Shipment 
        
        shipment = Shipment.query.filter_by(shipment_id=data['shipment_id']).first()
        if shipment:
            shipment.ups_tracking_id = data['tracking_id']
            db.session.commit()
            success = True
            message = "Tracking number updated successfully"
        else:
            success = False
            message = "Shipment not found"
    except Exception as e:
        db.session.rollback() # Ensure rollback on error
        success = False
        message = str(e)
    
    return jsonify({
        'success': success,
        'message': message,
        'acks': acks
    })

@ups_bp.route('/status-update', methods=['POST'])
def handle_status_update():
    # Instantiate service INSIDE the route (needed for handle_package_delivered)
    shipment_service = ShipmentService() 
    
    data = request.json
    if not data or 'shipment_id' not in data or 'status' not in data:
        return jsonify({
            'success': False,
            'error': 'Missing required fields'
        }), 400
    
    acks = []
    if 'seqnum' in data:
        acks.append(data['seqnum'])
    
    try:
        # Import model here, inside the function
        from app.model import db, Shipment 
        
        shipment = Shipment.query.filter_by(shipment_id=data['shipment_id']).first()
        if shipment:
            if data['status'] == 'delivering':
                shipment.status = 'delivering'
                db.session.commit()
                success = True
                message = "Status updated successfully"
            elif data['status'] == 'delivered':
                # Use the locally instantiated service
                success, message = shipment_service.handle_package_delivered(data['shipment_id']) 
            else:
                success = False
                message = f"Unknown status: {data['status']}"
        else:
            success = False
            message = "Shipment not found"
    except Exception as e:
        db.session.rollback() # Ensure rollback on error
        success = False
        message = str(e)
    
    return jsonify({
        'success': success,
        'message': message,
        'acks': acks
    })