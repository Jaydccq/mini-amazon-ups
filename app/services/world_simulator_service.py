import socket
import threading
import time
import struct
import logging
import queue
from datetime import datetime
from google.protobuf.message import Message
from flask import current_app
import random

from app.model import db, WorldMessage, Warehouse
from google.protobuf.internal.encoder import _VarintBytes
from google.protobuf.internal.decoder import _DecodeVarint32
from app.proto import world_amazon_1_pb2 as amazon_pb2


logger = logging.getLogger(__name__)

class WorldSimulatorService:
    def __init__(self, app=None, host='server', port=23456):
        self.app = app
        self.host = host
        self.port = port
        self.socket = None
        self.connected = False
        self.world_id = None
        self.seqnum = 0
        self.lock = threading.Lock()
        self.acks = set()
        self.pending_responses = {}
        self.response_events = {}
        self.message_queue = queue.Queue()
        self.running = True
        
    #     self._load_last_seqnum()
    
    # # Load the last used sequence number 
    # def _load_last_seqnum(self):
    #     last_message = WorldMessage.query.order_by(WorldMessage.seqnum.desc()).first()
    #     if last_message:
    #         with self.lock:
    #             self.seqnum = last_message.seqnum

    # Get the next sequence number    
    def _get_next_seqnum(self):
        # Try to load the last sequence number if we haven't yet
        # if self.seqnum == 0:
        #     try:
        #         from flask import current_app
        #         with current_app.app_context():
        #             self._load_last_seqnum()
        #     except Exception:
        #         # Continue with default if we can't access the database
        #         pass
                
        with self.lock:
            self.seqnum += 1
            return self.seqnum
    
    # Connect to the world simulator
    def connect(self, world_id=None, init_warehouses=None):
        
        try:
            self.cleanup_old_world_messages()
            logger.info(f"Connecting to World Simulator at {self.host}:{self.port}...")
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect(('docker_deploy-server-1', self.port))
            logger.info("Connected to World Simulator")
            # Create connection message
            connect_msg = amazon_pb2.AConnect()
            connect_msg.isAmazon = True

            default_init_warehouses = []
            for i in range(1, 51):
                one_warehouse = Warehouse()
                one_warehouse.warehouse_id = i
                one_warehouse.x = random.randint(10, 100)
                one_warehouse.y = random.randint(10, 100)
                default_init_warehouses.append(one_warehouse)

            init_warehouses =  default_init_warehouses
            default_speed_command = amazon_pb2.ACommands()
            default_speed_command.simspeed = 1000
            self.queue_command(default_speed_command)
            print(connect_msg)
            if world_id:
                connect_msg.worldid = world_id
            
            if init_warehouses:
                for wh in init_warehouses:
                    new_wh = connect_msg.initwh.add()
                    new_wh.id = wh.warehouse_id
                    new_wh.x = wh.x
                    new_wh.y = wh.y
            
            # Send connection message
            self.send_protobuf(connect_msg)
            
            # Receive 
            data = self.receive_message()
            # connect response
            response = amazon_pb2.AConnected()
            response.ParseFromString(data)
            
            self.world_id = response.worldid
            self.connected = response.result == "connected!"
            
            if not self.connected:
                logger.error(f"Failed to connect to World Simulator: {response.result}")
                return None, response.result

            # Initialize the database with the initial warehouses
            if init_warehouses:
                # Clear existing warehouses
                db.session.query(Warehouse).delete()
                for wh in init_warehouses:
                    wh.world_id = self.world_id
                    db.session.add(wh)
                db.session.commit()
            
            # receiver_thread
            self.receiver_thread = threading.Thread(target=self.receive_loop)
            self.receiver_thread.daemon = True
            self.receiver_thread.start()
            # sender_thread
            self.sender_thread = threading.Thread(target=self._send_loop)
            self.sender_thread.daemon = True
            self.sender_thread.start()
            
            logger.info(f"Connected to World Simulator with world_id {self.world_id}")
            
            return self.world_id, response.result
        except Exception as e:
            logger.error(f"Error connecting to World Simulator: {e}")
            return None, str(e)
    
    def disconnect(self):
        try:
            if self.connected:
                # disconnect command
                command = amazon_pb2.ACommands()
                command.disconnect = True
                self.queue_command(command)
                
                # Wait for threads to finish
                self.running = False
                if self.sender_thread:
                    self.sender_thread.join(timeout=5)
                if self.receiver_thread:
                    self.receiver_thread.join(timeout=5)
                
                # Close socket
                self.socket.close()
                self.connected = False

                # delete all warehouses
                db.session.query(Warehouse).delete()
                db.session.commit()
                
                logger.info("Disconnected from World Simulator")
        except Exception as e:
            logger.error(f"Error disconnecting from World Simulator: {e}")
    
    # Modify in app/services/world_simulator_service.py
    def buy_product(self, warehouse_id, product_id, description, quantity):
        if not self.connected:
            return False, "Not connected to World Simulator"
        
        try:
            command = amazon_pb2.ACommands()
            buy = command.buy.add()
            buy.whnum = warehouse_id
            buy.seqnum = self._get_next_seqnum()
            
            product = buy.things.add()
            product.id = product_id
            truncated_description = description[:50]
            product.description = truncated_description
            if len(description) > 50:
                logger.warning(f"Truncated description for product {product_id} from '{description}' to '{truncated_description}' before sending buy command.")
            product.count = quantity
            
            db_message = WorldMessage(
                seqnum=buy.seqnum,
                message_type='buy',
                message_content=f"Warehouse: {warehouse_id}, Product: {product_id}, Quantity: {quantity}",
                status='sent'
            )
            db.session.add(db_message)
            db.session.commit()
            
            # Queue the command without waiting for response
            self.queue_command(command)
            
            # Return success immediately - we'll get notification later when products arrive
            return True, "Replenishment request sent successfully"
            
        except Exception as e:
            logger.error(f"Error buying product: {e}")
            return False, str(e)
    
    def pack_shipment(self, warehouse_id, shipment_id, items):
        if not self.connected:
            return False, "Not connected to World Simulator"
        
        try:
            command = amazon_pb2.ACommands()
            pack = command.topack.add()
            pack.whnum = warehouse_id
            pack.shipid = shipment_id
            pack.seqnum = self._get_next_seqnum()
            
            for item in items:
                product = pack.things.add()
                product.id = item['product_id']
                product.description = item['description']
                product.count = item['quantity']
            
            # save command to database
            db_message = WorldMessage(
                seqnum=pack.seqnum,
                message_type='topack',
                message_content=f"Warehouse: {warehouse_id}, Shipment: {shipment_id}, Items: {len(items)}",
                status='sent'
            )
            db.session.add(db_message)
            db.session.commit()
            
            event = threading.Event()
            with self.lock:
                self.response_events[pack.seqnum] = event
            
            self.queue_command(command)
            
            if event.wait(timeout=10):
                with self.lock:
                    if pack.seqnum in self.pending_responses:
                        response = self.pending_responses[pack.seqnum]
                        del self.pending_responses[pack.seqnum]
                        del self.response_events[pack.seqnum]
                        return True, response
            
            return False, "Timeout waiting for response"
        except Exception as e:
            logger.error(f"Error packing shipment: {e}")
            return False, str(e)
    
    def load_shipment(self, warehouse_id, truck_id, shipment_id):
        if not self.connected:
            return False, "Not connected to World Simulator"
        
        try:
            command = amazon_pb2.ACommands()
            load = command.load.add()
            load.whnum = warehouse_id
            load.truckid = truck_id
            load.shipid = shipment_id
            load.seqnum = self._get_next_seqnum()
            
            # Save command to database
            db_message = WorldMessage(
                seqnum=load.seqnum,
                message_type='load',
                message_content=f"Warehouse: {warehouse_id}, Truck: {truck_id}, Shipment: {shipment_id}",
                status='sent'
            )
            db.session.add(db_message)
            db.session.commit()
            
            # ceate event sequence number
            event = threading.Event()
            with self.lock:
                self.response_events[load.seqnum] = event
            
            # queue the command
            self.queue_command(command)
            
            if event.wait(timeout=10):
                with self.lock:
                    if load.seqnum in self.pending_responses:
                        response = self.pending_responses[load.seqnum]
                        del self.pending_responses[load.seqnum]
                        del self.response_events[load.seqnum]
                        return True, response
            
            return False, "Timeout waiting for response"
        except Exception as e:
            logger.error(f"Error loading shipment: {e}")
            return False, str(e)
    
    def query_package(self, package_id):
        if not self.connected:
            return False, "Not connected to World Simulator"
        
        try:
            command = amazon_pb2.ACommands()
            query = command.queries.add()
            query.packageid = package_id
            query.seqnum = self._get_next_seqnum()
            
            db_message = WorldMessage(
                seqnum=query.seqnum,
                message_type='query',
                message_content=f"Package: {package_id}",
                status='sent'
            )
            db.session.add(db_message)
            db.session.commit()
            
            # create event sequence number
            event = threading.Event()
            with self.lock:
                self.response_events[query.seqnum] = event
            
            self.queue_command(command)
            
            if event.wait(timeout=10):
                with self.lock:
                    if query.seqnum in self.pending_responses:
                        response = self.pending_responses[query.seqnum]
                        del self.pending_responses[query.seqnum]
                        del self.response_events[query.seqnum]
                        return True, response
            
            return False, "Timeout waiting for response"
        except Exception as e:
            logger.error(f"Error querying package: {e}")
            return False, str(e)
    
    def queue_command(self, command):
        # Add acks for received messages
        with self.lock:
            for ack in self.acks:
                command.acks.append(ack)
            self.acks.clear()
        
        # Queue the command
        self.message_queue.put(command)
    
    def _send_loop(self):
        """Background thread for sending commands"""
        while self.running:
            try:
                # Get next command from queue
                try:
                    command = self.message_queue.get(timeout=1)
                except queue.Empty:
                    continue
                
                # Send the command
                self.send_protobuf(command)
                
                # Mark as done
                self.message_queue.task_done()
            except Exception as e:
                logger.error(f"Error in send loop: {e}")
                time.sleep(1)  # Avoid tight loop on error
    
    def receive_loop(self):
        last_heartbeat = time.time()
        
        while self.running:
            try:
                # Periodic heartbeat log
                current_time = time.time()
                if current_time - last_heartbeat > 5:
                    logger.debug("Receive loop is alive...")
                    last_heartbeat = current_time
                    
                data = self.receive_message()
                if not data:
                    logger.warning("Empty response received")
                    time.sleep(1) 
                    continue

                logger.info(f"Received raw data of length: {len(data)}")
                
                # Try to parse and log the response for debugging
                try:
                    response = amazon_pb2.AResponses()
                    response.ParseFromString(data)
                    logger.info(f"Parsed AResponses: ACKs received: {list(response.acks)}, "
                               f"Arrived: {len(response.arrived)}, Ready: {len(response.ready)}, "
                               f"Loaded: {len(response.loaded)}, Errors: {len(response.error)}")
                except Exception as parse_err:
                    logger.error(f"Failed to parse received data: {parse_err}")
                
                # Normal processing continues
                response = amazon_pb2.AResponses()
                response.ParseFromString(data)

                if self.app:
                    with self.app.app_context():
                        self.process_response(response) 
                else:
                    logger.error("WorldSimulatorService was not initialized with a Flask app object. Cannot create app context in receive_loop.")
            
            except ConnectionAbortedError:
                logger.warning("Connection aborted, stopping receive loop.")
                self.running = False
            except socket.timeout:
                logger.debug("Socket receive timed out, continuing loop.")
                continue 
            except Exception as e:
                logger.error(f"Error in receive loop: {e}", exc_info=True)
                if not self.running:
                    break
                time.sleep(1)
    

    def process_response(self, response):
        try:
            acks_to_send = []

            for ack_seqnum in response.acks:
                logger.info(f"Processing ACK received from world for seqnum: {ack_seqnum}")
                self.process_ack(ack_seqnum) 

            for package in response.arrived:
                self.process_arrived(package) 
                acks_to_send.append(package.seqnum) 

            for package in response.ready:
                self.process_ready(package)
                acks_to_send.append(package.seqnum) 

            for package in response.loaded:
                self.process_loaded(package) 
                acks_to_send.append(package.seqnum)

            for package in response.packagestatus:
                self.process_package_status(package) 
                acks_to_send.append(package.seqnum) 

            for error in response.error:
                self.process_error(error) 
                acks_to_send.append(error.seqnum) 


            with self.lock:
                 self.acks.update(acks_to_send)

        except Exception as e:
            logger.error(f"Error processing response content: {e}", exc_info=True)


    def process_ack(self, seqnum):
        logger.debug(f"Received ack for seqnum {seqnum}")
        
        logger.info(f"Attempting to find WorldMessage for acked seqnum {seqnum}...")
        message = WorldMessage.query.filter_by(seqnum=seqnum).first()
        if message:
            logger.info(f"Found WorldMessage ID {message.id}, current status {message.status}. Setting status to 'acked'.")
            message.status = 'acked'
            try:
                db.session.commit()
                logger.info(f"Successfully committed status update for WorldMessage ID {message.id}, seqnum {seqnum}.")
            except Exception as commit_err:
                db.session.rollback()
                logger.error(f"Failed to commit status update for seqnum {seqnum}: {commit_err}", exc_info=True)
        else:
            logger.warning(f"Could not find WorldMessage in DB for acked seqnum {seqnum}.")
        
        with self.lock:
            # Only set the event if it exists in the dictionary
            if seqnum in self.response_events:
                if seqnum not in self.pending_responses or self.pending_responses[seqnum] is None:
                    self.pending_responses[seqnum] = "ACK"
                self.response_events[seqnum].set()
                logger.info(f"Set event for seqnum {seqnum}")
            else:
                # Just log a message - this is expected for asynchronous commands
                logger.debug(f"No event waiting for ack of seqnum {seqnum}")
    
    def process_arrived(self, package):
        logger.info(f"Products arrived for warehouse {package.whnum}")
        from app.services.world_event_handler import WorldEventHandler

        handler = WorldEventHandler(self.app)
        for product in package.things:
            handler.handle_world_event('product_arrived', {
                'warehouse_id': package.whnum,
                'product_id': product.id,
                'description': product.description,
                'quantity': product.count
            })
        
        with self.lock:
            self.acks.add(package.seqnum)
    
    def process_ready(self, package):
        logger.info(f"Package {package.shipid} is ready")
        from app.services.world_event_handler import WorldEventHandler

        handler = WorldEventHandler(self.app)
        handler.handle_world_event('package_ready', {
            'shipment_id': package.shipid
        })
        with self.lock:
            self.acks.add(package.seqnum)
    
    def process_loaded(self, package):
        logger.info(f"Package {package.shipid} is loaded")
        
        from app.model import Shipment
        shipment = Shipment.query.filter_by(shipment_id=package.shipid).first()
        
        if shipment and shipment.truck_id:
            from app.services.world_event_handler import WorldEventHandler
            handler = WorldEventHandler(self.app)
            handler.handle_world_event('package_loaded', {
                'shipment_id': package.shipid,
                'truck_id': shipment.truck_id
            })
        
        with self.lock:
            self.acks.add(package.seqnum)
    
    def process_package_status(self, package):
        logger.info(f"Package {package.packageid} status: {package.status}")
        
        with self.lock:
            if package.seqnum in self.response_events:
                self.pending_responses[package.seqnum] = package.status
                self.response_events[package.seqnum].set()
        
        with self.lock:
            self.acks.add(package.seqnum)
    
    def process_error(self, error):
        logger.error(f"Error from world simulator: {error.err} (seqnum: {error.originseqnum})")
        
        # Store the error
        with self.lock:
            if error.originseqnum in self.response_events:
                self.pending_responses[error.originseqnum] = f"Error: {error.err}"
                self.response_events[error.originseqnum].set()
        
        with self.lock:
            self.acks.add(error.seqnum)
    
    def send_protobuf(self, message):
        # Add logging to track the message being sent
        try:
            seqnum = None
            if message.buy:
                seqnum = message.buy[0].seqnum
            elif message.topack:
                seqnum = message.topack[0].seqnum
            elif message.load:
                seqnum = message.load[0].seqnum
            elif message.queries:
                seqnum = message.queries[0].seqnum
                
            logger.info(f"Sending message with seqnum: {seqnum}, ACKs being sent: {list(message.acks)}")
        except Exception as e:
            logger.warning(f"Could not log message details: {e}")
            
        serialized = message.SerializeToString()
        # Use Varint32 encoding for message length
        size_prefix = _VarintBytes(len(serialized))
        # Send both length prefix and message in one call
        self.socket.sendall(size_prefix + serialized)
    
    # receive a message
    def receive_message(self):
        # Read the Varint32-encoded message length
        buf = b""
        while True:
            chunk = self.socket.recv(1)
            if not chunk:
                return None  # Connection closed
            buf += chunk
            try:
                message_size, new_pos = _DecodeVarint32(buf, 0)
                break
            except IndexError:
                continue  # Need more bytes for the varint
        
        # Receive the message data using existing recvall method
        return self.recvall(message_size)
    
    # Helper function to receive all data
    def recvall(self, n):
        data = b''
        while len(data) < n:
            packet = self.socket.recv(n - len(data))
            if not packet:
                return None
            data += packet
        return data
    
    def _reconnect_with_backoff(self):
        retry_count = 0
        max_retries = 5
        base_delay = 1  # seconds
        
        while retry_count < max_retries:
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.connect((self.host, self.port))
                return True
            except Exception as e:
                retry_count += 1
                delay = base_delay * (2 ** retry_count)
                logger.warning(f"Reconnection attempt {retry_count} failed. Retrying in {delay} seconds.")
                time.sleep(delay)
        
        return False
    



    def set_sim_speed(self, speed: int):

        if not self.connected:
            logger.error("Cannot set sim speed: Not connected to World Simulator")
            # Optionally raise an exception or return False
            return False

        if not isinstance(speed, int) or speed < 0:
             logger.error(f"Invalid simulation speed: {speed}. Speed must be a non-negative integer.")
             return False

        try:
            # Create the command message
            command = amazon_pb2.ACommands()
            command.simspeed = speed
            logger.info(f"Queueing command to set simulation speed to {speed}")

            # Queue the command for sending using the existing mechanism
            # queue_command already handles adding acks
            self.queue_command(command)
            return True

        except Exception as e:
            logger.error(f"Error creating or queueing set_sim_speed command: {e}", exc_info=True)
            return False
    def cleanup_old_world_messages(self):
        """
        Clean up old world messages from the database when initializing or connecting.
        This helps prevent accumulation of stale messages across different world connections.
        """
        try:
            # Option 1: Delete all existing WorldMessage records
            deleted_count = db.session.query(WorldMessage).delete()
            
            # Option 2: Delete messages older than a certain threshold (optional alternative)
            # from datetime import datetime, timedelta
            # threshold = datetime.utcnow() - timedelta(hours=24)
            # deleted_count = db.session.query(WorldMessage).filter(WorldMessage.created_at < threshold).delete()
            
            db.session.commit()
            logger.info(f"Cleaned up {deleted_count} old world messages")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error cleaning up world messages: {e}")
