from pyexpat.errors import messages

import requests
import json
import logging
from datetime import datetime
from flask import current_app
from app.model import db, UPSMessage, Shipment, Order

logger = logging.getLogger(__name__)

uri_map = {
    'ShipmentCreated': '/shipment/',
    'ShipmentLoaded': '/shipment_loaded/',
    'ShipmentStatusRequest': '/shipment_status/',
    # 'ShipmentStatusResponse': '/shipment_detail_response/',
}

class UPSIntegrationService:
    def __init__(self, ups_url='http://ups-service:8080/api'):
        self.ups_url = ups_url
        self.session = requests.Session()

    def notify_package_created(self, user_id, email, shipment_id, warehouse_id, destination_x, destination_y, ups_account=None):
        message = {
            "message_type": "ShipmentCreated",
            "timestamp": datetime.utcnow(),
            "payload": {
                'user_id': user_id,
                'email': email,
                'shipment_id': shipment_id,
                'warehouse_id': warehouse_id,
                "destination_x": destination_x,
                "destination_y": destination_y
            }
        }

        if ups_account:
            message['ups_account'] = ups_account

        # Save message to database
        db_message = UPSMessage(
            message_type='ShipmentCreated',
            timestamp=datetime.utcnow(),
            pay_load=json.dumps(message)
        )
        db.session.add(db_message)
        db.session.commit()

        # Send message immediately and return response
        success, response = self.send_message('ShipmentCreated', message)

        # Update message status in database
        db_message.status = 'success' if success else 'failed'

        if(response.get('payload').get('status') == 'success'):
            db_message.status = 'success'
            db.session.commit()
            return True, 'Order created successfully'
        else:
            db_message.status = 'failed'
            db.session.commit()
            return False, 'Order creation failed: '+response.get('payload').get('message')

    # Notify UPS that a package has been loaded
    def notify_package_loaded(self, shipment_id):
        message = {
            "message_type": "ShipmentLoaded",
              "timestamp": datetime.utcnow(),
              "payload": {
                "shipment_id": shipment_id
              }
        }

        # Save message to database
        db_message = UPSMessage(
            message_type='ShipmentLoaded',
            timestamp=datetime.utcnow(),
            message_content=json.dumps(message),
        )
        db.session.add(db_message)
        db.session.commit()

        # Send message immediately and return response
        success, response = self.send_message('ShipmentLoaded', message)

        # Update message status in database
        db_message.status = 'success' if success else 'failed'

        db.session.commit()

        return response

    # Handle truck arrival notification from UPS
    def get_shipment_status(self, shipment_id):
        try:

            # Query the shipment status from UPS
            message = {
                "message_type": "ShipmentStatusRequest",
                  "timestamp": datetime.utcnow(),
                  "payload": {
                    "shipment_id": shipment_id
                }
            }

            success, response = self.send_message('ShipmentStatusRequest', message)

            # Return success response
            return response

        except Exception as e:
            logger.error(f"Error handling truck arrival: {str(e)}")
            db.session.rollback()
            return False, str(e)

    def send_message(self, message_type, message_content):
        try:
            endpoint = f"{self.ups_url}/{message_type}"
            response = self.session.post(
                endpoint,
                json=message_content,
                timeout=10  # Increased timeout for blocking calls
            )

            if response.status_code == 200:
                return True, response.json()
            else:
                logger.error(f"UPS service responded with status {response.status_code}: {response.text}")
                return False, f"UPS service responded with status {response.status_code}: {response.text}"
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending message to UPS: {str(e)}")
            return False, f"Error sending message to UPS: {str(e)}"


