from flask import Blueprint, request, jsonify, current_app
from app.services.world_event_handler import WorldEventHandler
from app.services.ups_integration_service import UPSIntegrationService
from app.services.shipment_service import ShipmentService

# Create the blueprints
world_bp = Blueprint('world', __name__, url_prefix='/api/world')
ups_bp = Blueprint('ups', __name__, url_prefix='/api/ups')

# Initialize services
world_event_handler = WorldEventHandler()
ups_integration = UPSIntegrationService()
shipment_service = ShipmentService()

@world_bp.route('/event', methods=['POST'])
def handle_world_event():
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
    
    # Handle the event
    success, message = world_event_handler.handle_world_event(event_type, event_data)
    
    return jsonify({
        'success': success,
        'message': message,
        'acks': acks
    })

# UPS 卡车到达：/api/ups/truck-arrived
@ups_bp.route('/truck-arrived', methods=['POST'])
def handle_truck_arrived():
    """Endpoint for receiving truck arrived notifications from UPS"""
    data = request.json
    if not data or 'truck_id' not in data or 'warehouse_id' not in data:
        return jsonify({
            'success': False,
            'error': 'Missing required fields'
        }), 400
    
    # Process acknowledgments if present
    acks = []
    if 'seqnum' in data:
        acks.append(data['seqnum'])
    
    # Handle the truck arrival
    success = shipment_service.handle_truck_arrived(data['truck_id'], data['warehouse_id'])
    
    return jsonify({
        'success': success,
        'acks': acks
    })
#UPS 包裹已送达：/api/ups/package-delivered
@ups_bp.route('/package-delivered', methods=['POST'])
def handle_package_delivered():
    """Endpoint for receiving package delivered notifications from UPS"""
    data = request.json
    if not data or 'shipment_id' not in data:
        return jsonify({
            'success': False,
            'error': 'Missing required fields'
        }), 400
    
    acks = []
    if 'seqnum' in data:
        acks.append(data['seqnum'])
    
    success, message = shipment_service.handle_package_delivered(data['shipment_id'])
    
    return jsonify({
        'success': success,
        'message': message,
        'acks': acks
    })

# UPS 记录追踪号：/api/ups/tracking
@ups_bp.route('/tracking', methods=['POST'])
def add_tracking_number():
    """Endpoint for UPS to provide tracking number for a shipment"""
    data = request.json
    if not data or 'shipment_id' not in data or 'tracking_id' not in data:
        return jsonify({
            'success': False,
            'error': 'Missing required fields'
        }), 400
    
    # Process acknowledgments if present
    acks = []
    if 'seqnum' in data:
        acks.append(data['seqnum'])
    
    try:
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
        success = False
        message = str(e)
    
    return jsonify({
        'success': success,
        'message': message,
        'acks': acks
    })

#UPS 包裹状态更新：/api/ups/status-update
@ups_bp.route('/status-update', methods=['POST'])
def handle_status_update():
    data = request.json
    if not data or 'shipment_id' not in data or 'status' not in data:
        return jsonify({
            'success': False,
            'error': 'Missing required fields'
        }), 400
    
    # Process acknowledgments if present
    acks = []
    if 'seqnum' in data:
        acks.append(data['seqnum'])
    
    try:
        # Update status in shipment
        from app.model import db, Shipment
        
        shipment = Shipment.query.filter_by(shipment_id=data['shipment_id']).first()
        if shipment:
            if data['status'] == 'delivering':
                shipment.status = 'delivering'
                db.session.commit()
                success = True
                message = "Status updated successfully"
            elif data['status'] == 'delivered':
                success, message = shipment_service.handle_package_delivered(data['shipment_id'])
            else:
                success = False
                message = f"Unknown status: {data['status']}"
        else:
            success = False
            message = "Shipment not found"
    except Exception as e:
        success = False
        message = str(e)
    
    return jsonify({
        'success': success,
        'message': message,
        'acks': acks
    })