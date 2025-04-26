from pyexpat.errors import messages

import requests
import json
import logging
from datetime import datetime
from flask import current_app
from app.model import db, UPSMessage, Shipment, Order

import json 
from app.model import db, UPSMessage 
from datetime import datetime 

logger = logging.getLogger(__name__)

uri_map = {
    'ShipmentCreated': 'shipment',
    'ShipmentLoaded': 'shipment_loaded',
    'ShipmentStatusRequest': 'shipment_status',
    'AddressChange': 'address_change',
    # 'ShipmentStatusResponse': '/shipment_detail_response/',
}

class UPSIntegrationService:
    def __init__(self, ups_url='http://host.docker.internal:8081/api'):
        self.ups_url = ups_url
        self.session = requests.Session()

# In app/services/ups_integration_service.py

    def notify_package_created(self, user_id, email, shipment_id, warehouse_id, destination_x, destination_y, ups_account=None):
        # 1. Define the core payload data
        message_payload = {
            'user_id': user_id,
            'email': email,
            'shipment_id': shipment_id,
            'warehouse_id': warehouse_id,
            "destination_x": destination_x,
            "destination_y": destination_y
        }
        if ups_account:
            message_payload['ups_account'] = ups_account # Add optional field

        # 2. Log *only* the payload data before sending
        self._log_ups_message('ShipmentCreated', message_payload, status='sent') # Log the payload dict

        # 3. Prepare the full message structure for the API call
        message_to_send = {
            "message_type": "ShipmentCreated",
            "timestamp": datetime.utcnow().isoformat(), # Generate timestamp for the API call
            "payload": message_payload # Embed the payload
        }

        # 4. Send the correctly structured message
        success, response = self.send_message('ShipmentCreated', message_to_send) # Send message_to_send

        logger.info(f"UPS response: {response}")

        # 5. Handle the response (with safer error message extraction)
        if success and response.get('payload', {}).get('status') == 'success':
            # Optionally update the logged message status to 'acked' here if desired
            return True, 'Order created successfully'
        else:
            # Safer error message retrieval
            error_message = response.get('payload', {}).get('message', 'Unknown error') if isinstance(response, dict) else str(response)
            # Optionally update the logged message status to 'failed' here
            return False, f'Order creation failed: {error_message}' # Use the extracted message


    # def notify_package_created(self, user_id, email, shipment_id, warehouse_id, destination_x, destination_y, ups_account=None):
    #     message = {
    #         "message_type": "ShipmentCreated",
    #         "timestamp": datetime.utcnow().isoformat(),
    #         "payload": {
    #             'user_id': user_id,
    #             'email': email,
    #             'shipment_id': shipment_id,
    #             'warehouse_id': warehouse_id,
    #             "destination_x": destination_x,
    #             "destination_y": destination_y
    #         }
    #     }

    #     if ups_account:
    #         message['ups_account'] = ups_account

    #     # Save message to database
    #     # db_message = UPSMessage(
    #     #     message_type='ShipmentCreated',
    #     #     timestamp=datetime.utcnow().isoformat(),
    #     #     pay_load=json.dumps(message)
    #     # )
    #     # db.session.add(db_message)
    #     # db.session.commit()

    #     # Send message immediately and return response
    #     success, response = self.send_message('ShipmentCreated', message)

    #     logger.info(f"UPS response: {response}")

    #     if(response.get('payload').get('status') == 'success'):
    #         return True, 'Order created successfully'
    #     else:
    #         return False, 'Order creation failed: '+response.get('payload').get('message')

    # Notify UPS that a package has been loaded
    def notify_package_loaded(self, shipment_id):
        message_payload = {"shipment_id": shipment_id}
        self._log_ups_message('ShipmentLoaded', message_payload, status='sent') # 

        message = {
            "message_type": "ShipmentLoaded",
              "timestamp": datetime.utcnow().isoformat(),
              "payload": {
                "shipment_id": shipment_id
              }
        }

        # Save message to database
        # db_message = UPSMessage(
        #     message_type='ShipmentLoaded',
        #     timestamp=datetime.utcnow().isoformat(),
        #     message_content=json.dumps(message),
        # )
        # db.session.add(db_message)
        # db.session.commit()

        # Send message immediately and return response
        message_to_send = {
                "message_type": "ShipmentLoaded",
                "timestamp": datetime.utcnow().isoformat(),
                "payload": message_payload
            }
        success, response = self.send_message('ShipmentLoaded', message_to_send)
    
        return response

    # Handle truck arrival notification from UPS
    def get_shipment_status(self, shipment_id):
        try:

            # Query the shipment status from UPS
            message = {
                "message_type": "ShipmentStatusRequest",
                  "timestamp": datetime.utcnow().isoformat(),
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
            endpoint = f"{self.ups_url}/{uri_map.get(message_type)}"
            logger.info(f"Sending message to UPS: {message_content} to {endpoint}")
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


    def _log_ups_message(self, message_type, payload, status='sent', seqnum=None):
        try:
            payload_str = json.dumps(payload) if isinstance(payload, dict) else str(payload)

            timestamp = payload.get('timestamp', datetime.utcnow().isoformat())
            try:
                if isinstance(timestamp, str):
                    timestamp = timestamp.replace('Z', '+00:00') # Handle Z timezone indicator
                    timestamp_dt = datetime.fromisoformat(timestamp)
                elif isinstance(timestamp, (int, float)): # Handle potential Unix timestamps
                    timestamp_dt = datetime.utcfromtimestamp(timestamp)
                else:
                    timestamp_dt = datetime.utcnow() 
            except (ValueError, TypeError):
                timestamp_dt = datetime.utcnow() 


            log_entry = UPSMessage(
                message_type=message_type, # Log the specific type being sent/received
                timestamp=timestamp_dt,
                payload=payload_str,
                status=status,
                seqnum=seqnum # Include seqnum if applicable
            )
            db.session.add(log_entry)
            db.session.commit()
            logger.info(f"Logged UPS message: Type={message_type}, Status={status}")
            return True
        except Exception as log_e:
            db.session.rollback()
            logger.error(f"Failed to log UPS message ({message_type}, {status}): {log_e}", exc_info=True)
            return False
        
        
    def notify_address_change(self, shipment_id, destination_x, destination_y):
        message_payload = {
            "shipment_id": shipment_id,
            "destination_x": destination_x,
            "destination_y": destination_y
        }
        
        self._log_ups_message('AddressChange', message_payload, status='sent')
        
        message_to_send = {
            "message_type": "AddressChange",
            "timestamp": datetime.utcnow().isoformat(),
            "payload": message_payload
        }
        
        success, response = self.send_message('AddressChange', message_to_send)
        
        if success and response.get('payload', {}).get('status') == 'success':
            return True, 'Address updated successfully'
        else:
            error_message = response.get('payload', {}).get('message', 'Unknown error') if isinstance(response, dict) else str(response)
            return False, f'Address update failed: {error_message}'