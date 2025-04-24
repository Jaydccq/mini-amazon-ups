from flask import Blueprint, request, jsonify

from app.controllers.amazon_controller import shipment_service
from app.model import db, Shipment, Order, Warehouse, Product, ShipmentItem
from datetime import datetime
import logging
import ups_integration_service
from app.services.shipment_service import ShipmentService

logger = logging.getLogger(__name__)

# Create a Blueprint for UPS webhook endpoints
ups_webhooks = Blueprint('ups_webhooks', __name__, url_prefix='/api/ups/webhooks')
shipment_service_instance = ShipmentService();

@ups_webhooks.route('/truck-dispatched', methods=['POST'])
def truck_dispatched():
    """
    UPS notifies Amazon that a truck has been dispatched
    """
    try:
        message = request.get_json()

        # Validate message structure
        if not validate_message_structure(message, 'TruckDispatched'):
            return jsonify({
                'message_type': 'Error',
                'timestamp': datetime.utcnow().isoformat(),
                'payload': {
                    'error_code': 400,
                    'error_message': 'Invalid message structure'
                }
            }), 400

        # Extract data
        payload = message.get('payload', {})
        truck_id = payload.get('truck_id')
        shipment_id = payload.get('shipment_id')

        # Check if shipment exists
        shipment = Shipment.query.filter_by(shipment_id=shipment_id).first()
        if not shipment:
            return jsonify({
                'message_type': 'Error',
                'timestamp': datetime.utcnow().isoformat(),
                'payload': {
                    'original_sequence_number': message.get('sequence_number'),
                    'error_code': 404,
                    'error_message': f'Shipment {shipment_id} not found'
                }
            }), 404

        # Update shipment with truck information
        shipment.truck_id = truck_id
        shipment.status = 'truck_dispatched'
        shipment.updated_at = datetime.utcnow()

        db.session.commit()

        logger.info(f"Truck {truck_id} dispatched for shipment {shipment_id}")

        return jsonify({
            'message_type': 'Acknowledgement',
            'timestamp': datetime.utcnow().isoformat(),
            'payload': {
                'original_sequence_number': message.get('sequence_number'),
                'status': 'success'
            }
        })

    except Exception as e:
        logger.error(f"Error processing truck dispatch notification: {str(e)}")
        return jsonify({
            'message_type': 'Error',
            'timestamp': datetime.utcnow().isoformat(),
            'payload': {
                'original_sequence_number': message.get('sequence_number', 0),
                'error_code': 500,
                'error_message': str(e)
            }
        }), 500


@ups_webhooks.route('/truck-arrived', methods=['POST'])
def truck_arrived():
    """
    UPS notifies Amazon that a truck has arrived at warehouse
    """
    try:
        message = request.get_json()

        # Validate message structure
        if not validate_message_structure(message, 'TruckArrived'):
            return jsonify({
                'message_type': 'Error',
                'timestamp': datetime.utcnow().isoformat(),
                'payload': {
                    'error_code': 400,
                    'error_message': 'Invalid message structure'
                }
            }), 400

        # Extract data
        payload = message.get('payload', {})
        truck_id = payload.get('truck_id')
        warehouse_id = payload.get('warehouse_id')
        shipment_id = payload.get('shipment_id')

        # Check if warehouse exists
        warehouse = Warehouse.query.filter_by(warehouse_id=warehouse_id).first()
        if not warehouse:
            return jsonify({
                'message_type': 'Error',
                'timestamp': datetime.utcnow().isoformat(),
                'payload': {
                    'error_code': 404,
                    'error_message': f'Warehouse {warehouse_id} not found'
                }
            }), 404

        # Update shipment status
        shipment = Shipment.query.filter_by(shipment_id=shipment_id).first()
        if not shipment:
            return jsonify({
                'message_type': 'Error',
                'timestamp': datetime.utcnow().isoformat(),
                'payload': {
                    'error_code': 404,
                    'error_message': f'Shipment {shipment_id} not found'
                }
            }), 404

        shipment.status = 'ready_for_loading'
        shipment.updated_at = datetime.utcnow()

        db.session.commit()

        logger.info(f"Truck {truck_id} arrived at warehouse {warehouse_id} for shipment {shipment_id}")


        # async call
        # TODO: load pakages to truck (world)

        shipment_service_instance.handle_truck_arrived(
            truck_id=truck_id,
            warehouse_id=warehouse_id
        )

        return jsonify({
            'message_type': 'Acknowledgement',
            'timestamp': datetime.utcnow().isoformat(),
            'payload': {
                'status': 'success'
            }
        })

    except Exception as e:
        logger.error(f"Error processing truck arrival notification: {str(e)}")
        db.session.rollback()
        return jsonify({
            'message_type': 'Error',
            'timestamp': datetime.utcnow().isoformat(),
            'payload': {
                'error_code': 500,
                'error_message': str(e)
            }
        }), 500


@ups_webhooks.route('/shipment-delivered', methods=['POST'])
def shipment_delivered():
    """
    UPS notifies Amazon that a shipment has been delivered
    """
    try:
        message = request.get_json()

        # Validate message structure
        if not validate_message_structure(message, 'ShipmentDelivered'):
            return jsonify({
                'message_type': 'Error',
                'timestamp': datetime.utcnow().isoformat(),
                'payload': {
                    'error_code': 400,
                    'error_message': 'Invalid message structure'
                }
            }), 400

        # Extract data
        payload = message.get('payload', {})
        shipment_id = payload.get('shipment_id')
        sequence_number = message.get('sequence_number')

        # Update shipment status
        shipment = Shipment.query.filter_by(shipment_id=shipment_id).first()
        if not shipment:
            return jsonify({
                'message_type': 'Error',
                'timestamp': datetime.utcnow().isoformat(),
                'payload': {
                    'original_sequence_number': sequence_number,
                    'error_code': 404,
                    'error_message': f'Shipment {shipment_id} not found'
                }
            }), 404

        shipment.status = 'delivered'
        shipment.delivery_time = datetime.utcnow()
        shipment.updated_at = datetime.utcnow()

        # Update order status if all shipments delivered
        order = Order.query.filter_by(order_id=shipment.order_id).first()
        if order:
            all_shipments = Shipment.query.filter_by(order_id=order.order_id).all()
            all_delivered = all(s.status == 'delivered' for s in all_shipments)

            if all_delivered:
                order.order_status = 'Fulfilled'
                order.updated_at = datetime.utcnow()

        db.session.commit()

        logger.info(f"Shipment {shipment_id} delivered")

        return jsonify({
            'message_type': 'Acknowledgement',
            'timestamp': datetime.utcnow().isoformat(),
            'payload': {
                'original_sequence_number': sequence_number,
                'status': 'success'
            }
        })

    except Exception as e:
        logger.error(f"Error processing shipment delivery notification: {str(e)}")
        db.session.rollback()
        return jsonify({
            'message_type': 'Error',
            'timestamp': datetime.utcnow().isoformat(),
            'payload': {
                'original_sequence_number': message.get('sequence_number', 0),
                'error_code': 500,
                'error_message': str(e)
            }
        }), 500


@ups_webhooks.route('/shipment-detail-request', methods=['POST'])
def shipment_detail_request():
    """
    UPS requests details of a shipment
    """
    try:
        message = request.get_json()

        # Validate message structure
        if not validate_message_structure(message, 'PackageDetailRequest'):
            return jsonify({
                'message_type': 'Error',
                'timestamp': datetime.utcnow().isoformat(),
                'payload': {
                    'error_code': 400,
                    'error_message': 'Invalid message structure'
                }
            }), 400

        # Extract data
        payload = message.get('payload', {})
        shipment_id = payload.get('shipment_id')
        email_id = payload.get('email_id')

        # Retrieve shipment details
        shipment = Shipment.query.filter_by(shipment_id=shipment_id).first()
        if not shipment:
            return jsonify({
                'message_type': 'Error',
                'timestamp': datetime.utcnow().isoformat(),
                'payload': {
                    'error_code': 404,
                    'error_message': f'Shipment {shipment_id} not found'
                }
            }), 404

        # Get shipment items
        items = []
        shipment_items = ShipmentItem.query.filter_by(shipment_id=shipment_id).all()

        for item in shipment_items:
            product = Product.query.filter_by(product_id=item.product_id).first()
            if product:
                items.append({
                    'product_id': item.product_id,
                    'description': product.description,
                    'quantity': item.quantity
                })

        # Return shipment details response
        return jsonify({
            'message_type': 'ShipmentDetailResponse',
            'timestamp': datetime.utcnow().isoformat(),
            'payload': {
                'shipment_id': shipment.shipment_id,
                'warehouse_id': shipment.warehouse_id,
                'destination_x': shipment.destination_x,
                'destination_y': shipment.destination_y,
                'items': items
            }
        })

    except Exception as e:
        logger.error(f"Error processing shipment detail request: {str(e)}")
        return jsonify({
            'message_type': 'Error',
            'timestamp': datetime.utcnow().isoformat(),
            'payload': {
                'error_code': 500,
                'error_message': str(e)
            }
        }), 500


def validate_message_structure(message, expected_type):
    """
    Validate that the message has the expected structure and type
    """
    # Check basic structure
    if not isinstance(message, dict):
        return False

    # Check required fields
    if 'message_type' not in message or 'timestamp' not in message or 'payload' not in message:
        return False

    # Check message type
    if message.get('message_type') != expected_type:
        return False

    # Check payload is a dictionary
    if not isinstance(message.get('payload'), dict):
        return False

    # Specific validation for each message type
    payload = message.get('payload', {})

    if expected_type == 'TruckDispatched':
        return 'truck_id' in payload and 'shipment_id' in payload

    elif expected_type == 'TruckArrived':
        return 'truck_id' in payload and 'warehouse_id' in payload and 'shipment_id' in payload

    elif expected_type == 'ShipmentDelivered':
        return 'shipment_id' in payload

    elif expected_type == 'ShipmentStatusRequest':
        return 'shipment_id' in payload

    elif expected_type == 'PackageDetailRequest':
        return 'shipment_id' in payload

    return True

# You would register this blueprint in your Flask app