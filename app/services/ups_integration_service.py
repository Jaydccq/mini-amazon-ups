import requests
import threading
import json
import time
import logging
from datetime import datetime
from flask import current_app
from app.model import db, UPSMessage, Shipment, Order

logger = logging.getLogger(__name__)

class UPSIntegrationService:
    def __init__(self, ups_url='http://ups-service:8080/api'):
        self.ups_url = ups_url
        self.session = requests.Session()
        self.seqnum = 0
        self.lock = threading.Lock()
        self.acks = set()
        self.pending_messages = {}  # Store messages waiting for acks
        
        # Load last sequence number from database
        #self.load_last_seqnum()
        
        # Start background workers
        self.running = True
        self.message_processor = threading.Thread(target=self.process_pending_messages)
        self.message_processor.daemon = True
        self.message_processor.start()
    
    # def load_last_seqnum(self):
    #     last_message = UPSMessage.query.order_by(UPSMessage.seqnum.desc()).first()
    #     if last_message:
    #         with self.lock:
    #             self.seqnum = last_message.seqnum
    
    # def get_next_seqnum(self):
    #     with self.lock:
    #         self.seqnum += 1
    #         return self.seqnum

    def get_next_seqnum(self):
        # Try to load the last sequence number if we haven't yet
        if self.seqnum == 0:
            try:
                from flask import current_app
                with current_app.app_context():
                    self.load_last_seqnum()
            except Exception:
                # Continue with default if we can't access the database
                pass
                
        with self.lock:
            self.seqnum += 1
            return self.seqnum
    
    def notify_package_created(self, shipment_id, destination_x, destination_y, ups_account=None):
        seqnum = self.get_next_seqnum()
        
        message = {
            'shipment_id': shipment_id,
            'destination': {
                'x': destination_x,
                'y': destination_y
            },
            'seqnum': seqnum
        }
        
        if ups_account:
            message['ups_account'] = ups_account
        
        # Save message to database
        db_message = UPSMessage(
            seqnum=seqnum,
            message_type='package_created',
            message_content=json.dumps(message),
            status='sent'
        )
        db.session.add(db_message)
        db.session.commit()
        
        # Add to pending messages
        with self.lock:
            self.pending_messages[seqnum] = {
                'id': db_message.id,
                'message': message,
                'type': 'package_created',
                'retries': 0,
                'last_attempt': None
            }
        
        return seqnum
    
    # Notify UPS that a package has been packed
    def notify_package_packed(self, shipment_id):
        seqnum = self.get_next_seqnum()
        
        message = {
            'shipment_id': shipment_id,
            'seqnum': seqnum
        }
        
        # Save message to database
        db_message = UPSMessage(
            seqnum=seqnum,
            message_type='package_packed',
            message_content=json.dumps(message),
            status='sent'
        )
        db.session.add(db_message)
        db.session.commit()
        
        # Add to pending messages
        with self.lock:
            self.pending_messages[seqnum] = {
                'id': db_message.id,
                'message': message,
                'type': 'package_packed',
                'retries': 0,
                'last_attempt': None
            }
        
        return seqnum
    
    # Notify UPS that a package has been loaded onto a truck
    def notify_package_loaded(self, shipment_id, truck_id):
        seqnum = self.get_next_seqnum()
        
        message = {
            'shipment_id': shipment_id,
            'truck_id': truck_id,
            'seqnum': seqnum
        }
        
        db_message = UPSMessage(
            seqnum=seqnum,
            message_type='package_loaded',
            message_content=json.dumps(message),
            status='sent'
        )
        db.session.add(db_message)
        db.session.commit()
        
        # Add to pending messages
        with self.lock:
            self.pending_messages[seqnum] = {
                'id': db_message.id,
                'message': message,
                'type': 'package_loaded',
                'retries': 0,
                'last_attempt': None
            }
        
        return seqnum

    # Handle truck arrival notification from UPS    
    def handle_truck_arrived(self, data):
        try:
            truck_id = data.get('truck_id')
            warehouse_id = data.get('warehouse_id')
            seqnum = data.get('seqnum')
            
            if seqnum:
                self.process_ack(seqnum)
            
            # Update shipments packed status
            shipments = Shipment.query.filter_by(
                warehouse_id=warehouse_id,
                status='packed'
            ).all()
            
            for shipment in shipments:
                shipment.truck_id = truck_id       # Update shipment with truck_id

                shipment.status = 'loading'
                shipment.updated_at = datetime.utcnow()
            
            db.session.commit()
            
            # Return acknowledgment
            return True, "Truck arrival processed successfully"
        except Exception as e:
            logger.error(f"Error handling truck arrival: {str(e)}")
            db.session.rollback()
            return False, str(e)
    
    def handle_package_delivered(self, data):
        try:
            shipment_id = data.get('shipment_id')
            seqnum = data.get('seqnum')
            
            if seqnum:
                self.process_ack(seqnum)
            
            # Update shipment delivered status
            shipment = Shipment.query.filter_by(shipment_id=shipment_id).first()
            if not shipment:
                return False, "Shipment not found"
            
            shipment.status = 'delivered'
            shipment.updated_at = datetime.utcnow()
            
            #  update order status if all shipments are delivered
            order = Order.query.filter_by(order_id=shipment.order_id).first()
            if order:
                all_shipments = Shipment.query.filter_by(order_id=order.order_id).all()
                all_delivered = all(s.status == 'delivered' for s in all_shipments)
                
                if all_delivered:
                    order.order_status = 'Fulfilled'
            
            db.session.commit()
            
            return True, "Package delivery processed successfully"
        except Exception as e:
            logger.error(f"Error handling package delivery: {str(e)}")
            db.session.rollback()
            return False, str(e)
    
    def process_ack(self, seqnum):
        with self.lock:
            if seqnum in self.pending_messages:
                message_id = self.pending_messages[seqnum]['id']
                # Update message status in database
                db_message = UPSMessage.query.filter_by(id=message_id).first()
                if db_message:
                    db_message.status = 'acked'
                    db.session.commit()
                # Remove from pending messages
                del self.pending_messages[seqnum]
    
    def send_message(self, message_type, message_content):
        try:
            endpoint = f"{self.ups_url}/{message_type}"
            response = self.session.post(
                endpoint,
                json=message_content,
                timeout=5
            )
            
            if response.status_code == 200:
                response_data = response.json()
                # Process acknowledgments
                if 'acks' in response_data:
                    for ack in response_data['acks']:
                        self.process_ack(ack)
                return True, response_data
            else:
                return False, f"UPS service responded with status {response.status_code}: {response.text}"
        except requests.exceptions.RequestException as e:
            return False, f"Error sending message to UPS: {str(e)}"
    
    def process_pending_messages(self):
        while self.running:
            try:
                current_time = time.time()
                messages_to_retry = []
                
                with self.lock:
                    for seqnum, message_info in self.pending_messages.items():
                        if (message_info['last_attempt'] is None or 
                            current_time - message_info['last_attempt'] > 5):
                            messages_to_retry.append((seqnum, message_info))
                
                for seqnum, message_info in messages_to_retry:
                    message_type = message_info['type']
                    message = message_info['message']
                    
                    # Send the message
                    success, _ = self.send_message(message_type, message)
                    
                    with self.lock:
                        if seqnum in self.pending_messages:  
                            if success:
                                # Message sent successfully, wait for ack
                                self.pending_messages[seqnum]['last_attempt'] = current_time
                            else:
                                # Message failed
                                self.pending_messages[seqnum]['retries'] += 1
                                self.pending_messages[seqnum]['last_attempt'] = current_time
                                
                                # If too many retries, mark as failed
                                if self.pending_messages[seqnum]['retries'] >= 5:
                                    message_id = self.pending_messages[seqnum]['id']
                                    # Update message status
                                    db_message = UPSMessage.query.filter_by(id=message_id).first()
                                    if db_message:
                                        db_message.status = 'failed'
                                        db_message.retries = self.pending_messages[seqnum]['retries']
                                        db.session.commit()
                                    del self.pending_messages[seqnum]
            
            except Exception as e:
                logger.error(f"Error in UPS message processor: {str(e)}")
            
            # Sleep before next iteration
            time.sleep(1)
    
    def shutdown(self):
        self.running = False
        self.message_processor.join(timeout=5)