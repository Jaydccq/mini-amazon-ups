# app/controllers/webhook_controller.py

from flask import Blueprint, request, jsonify, current_app
from app.services.world_event_handler import WorldEventHandler
from app.services.ups_integration_service import UPSIntegrationService
from app.services.shipment_service import ShipmentService
from app.model import db, UPSMessage, Shipment
import json
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

world_bp = Blueprint('world', __name__, url_prefix='/api/world')
ups_bp = Blueprint('ups', __name__, url_prefix='/api/ups')


def log_incoming_ups_message(message_type, payload):
    try:
        timestamp = payload.get('timestamp', datetime.utcnow().isoformat())
        try:
            if isinstance(timestamp, str):
                 timestamp = timestamp.replace('Z', '+00:00')
                 timestamp_dt = datetime.fromisoformat(timestamp)
            elif isinstance(timestamp, (int, float)):
                 timestamp_dt = datetime.utcfromtimestamp(timestamp)
            else:
                 timestamp_dt = datetime.utcnow()
        except (ValueError, TypeError):
             timestamp_dt = datetime.utcnow()

        log_entry = UPSMessage(
            message_type=f"UPS_{message_type}_Received",
            timestamp=timestamp_dt,
            payload=json.dumps(payload),
            status='received',
            seqnum=payload.get('sequence_number', -1)
        )
        db.session.add(log_entry)
        db.session.commit()
        logger.info(f"Logged incoming UPS message: {message_type}")
    except Exception as log_e:
        db.session.rollback()
        logger.error(f"Failed to log incoming UPS webhook ({message_type}): {log_e}", exc_info=True)


@world_bp.route('/event', methods=['POST'])
def handle_world_event():
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

    success, message = world_event_handler.handle_world_event(event_type, event_data)

    return jsonify({
        'success': success,
        'message': message,
        'acks': acks
    })

@ups_bp.route('/truck-arrived', methods=['POST'])
def handle_truck_arrived():
    shipment_service = ShipmentService()

    data = request.json
    log_incoming_ups_message('TruckArrived', data)

    if not data or 'truck_id' not in data or 'warehouse_id' not in data:
        return jsonify({
            'success': False,
            'error': 'Missing required fields'
        }), 400

    acks = []
    if 'seqnum' in data:
        acks.append(data['seqnum'])

    success = shipment_service.handle_truck_arrived(data['truck_id'], data['warehouse_id'])

    return jsonify({
        'success': success,
        'acks': acks
    })

@ups_bp.route('/package-delivered', methods=['POST'])
def handle_package_delivered():
    shipment_service = ShipmentService()

    data = request.json
    log_incoming_ups_message('PackageDelivered', data)

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

@ups_bp.route('/tracking', methods=['POST'])
def add_tracking_number():
    data = request.json
    log_incoming_ups_message('TrackingInfo', data)

    if not data or 'shipment_id' not in data or 'tracking_id' not in data:
        return jsonify({
            'success': False,
            'error': 'Missing required fields'
        }), 400

    acks = []
    if 'seqnum' in data:
        acks.append(data['seqnum'])

    try:
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
        db.session.rollback()
        success = False
        message = str(e)
        logger.error(f"Error updating tracking number: {e}", exc_info=True)

    return jsonify({
        'success': success,
        'message': message,
        'acks': acks
    })

@ups_bp.route('/status-update', methods=['POST'])
def handle_status_update():
    shipment_service = ShipmentService()

    data = request.json
    log_incoming_ups_message('StatusUpdate', data)

    if not data or 'shipment_id' not in data or 'status' not in data:
        return jsonify({
            'success': False,
            'error': 'Missing required fields'
        }), 400

    acks = []
    if 'seqnum' in data:
        acks.append(data['seqnum'])

    try:
        shipment = Shipment.query.filter_by(shipment_id=data['shipment_id']).first()
        if shipment:
            valid_statuses = ['delivering', 'delivered']
            received_status = data['status'].lower()

            if received_status in valid_statuses:
                if received_status == 'delivering':
                    shipment.status = 'delivering'
                    db.session.commit()
                    success = True
                    message = "Status updated to delivering"
                elif received_status == 'delivered':
                    success, message = shipment_service.handle_package_delivered(data['shipment_id'])
                else:
                     success = False
                     message = f"Unhandled valid status: {received_status}"

            else:
                success = False
                message = f"Received unknown or invalid status from UPS: {data['status']}"
                logger.warning(f"Received invalid status '{data['status']}' for shipment {data['shipment_id']}")
        else:
            success = False
            message = "Shipment not found"
    except Exception as e:
        db.session.rollback()
        success = False
        message = str(e)
        logger.error(f"Error handling UPS status update: {e}", exc_info=True)

    return jsonify({
        'success': success,
        'message': message,
        'acks': acks
    })