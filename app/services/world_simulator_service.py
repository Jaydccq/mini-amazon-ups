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
from sqlalchemy import func
from app.model import db, User, ProductCategory, Cart, CartProduct,WarehouseProduct
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
        # self.acks = set()
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
    # def connect(self, world_id=None, init_warehouses=None):
        
    #     try:
    #         self.cleanup_old_world_messages()
    #         logger.info(f"Connecting to World Simulator at {self.host}:{self.port}...")
    #         self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    #         self.socket.connect(('docker_deploy-server-1', self.port))
    #         logger.info("Connected to World Simulator")
    #         # Create connection message
    #         connect_msg = amazon_pb2.AConnect()
    #         connect_msg.isAmazon = True

    #         default_init_warehouses = []
    #         for i in range(1, 51):
    #             one_warehouse = Warehouse()
    #             one_warehouse.warehouse_id = i
    #             one_warehouse.x = random.randint(10, 100)
    #             one_warehouse.y = random.randint(10, 100)
    #             default_init_warehouses.append(one_warehouse)

    #         init_warehouses =  default_init_warehouses
    #         default_speed_command = amazon_pb2.ACommands()
    #         default_speed_command.simspeed = 1000
    #         self.queue_command(default_speed_command)
    #         print(connect_msg)
    #         if world_id:
    #             connect_msg.worldid = world_id
            
    #         if init_warehouses:
    #             for wh in init_warehouses:
    #                 new_wh = connect_msg.initwh.add()
    #                 new_wh.id = wh.warehouse_id
    #                 new_wh.x = wh.x
    #                 new_wh.y = wh.y
            
    #         # Send connection message
    #         self.send_protobuf(connect_msg)
            
    #         # Receive 
    #         data = self.receive_message()
    #         # connect response
    #         response = amazon_pb2.AConnected()
    #         response.ParseFromString(data)
            
    #         self.world_id = response.worldid
    #         self.connected = response.result == "connected!"
            
    #         if not self.connected:
    #             logger.error(f"Failed to connect to World Simulator: {response.result}")
    #             return None, response.result

    #         # Initialize the database with the initial warehouses
    #         if init_warehouses:
    #             # Clear existing warehouses
    #             db.session.query(Warehouse).delete()
    #             for wh in init_warehouses:
    #                 wh.world_id = self.world_id
    #                 db.session.add(wh)
    #             db.session.commit()
            
    #         # receiver_thread
    #         self.receiver_thread = threading.Thread(target=self.receive_loop)
    #         self.receiver_thread.daemon = True
    #         self.receiver_thread.start()
    #         # sender_thread
    #         self.sender_thread = threading.Thread(target=self._send_loop)
    #         self.sender_thread.daemon = True
    #         self.sender_thread.start()
            
    #         logger.info(f"Connected to World Simulator with world_id {self.world_id}")
            
    #         return self.world_id, response.result
    #     except Exception as e:
    #         logger.error(f"Error connecting to World Simulator: {e}")
    #         return None, str(e)
    
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
            # db_message = WorldMessage(
            #     seqnum=load.seqnum,
            #     message_type='load',
            #     message_content=f"Warehouse: {warehouse_id}, Truck: {truck_id}, Shipment: {shipment_id}",
            #     status='sent'
            # )
            # db.session.add(db_message)
            # db.session.commit()
            
            # ceate event sequence number

            logger.info(f"Loading shipment {shipment_id} onto truck {truck_id} at warehouse {warehouse_id}")
            

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
    
    
    
    def queue_command(self, command):
        # Add acks for received messages
        # with self.lock:
        #     for ack in self.acks:
        #         command.acks.append(ack)
        #     self.acks.clear()
        
        # Queue the command
        self.message_queue.put(command)

    def _queue_ack_immediately(self, seqnum_to_ack):
        """Creates and queues an ACommands message containing only an ACK."""
        if not self.connected:
            logger.warning(f"Cannot queue ACK for {seqnum_to_ack}: Not connected.")
            return

        try:
            ack_command = amazon_pb2.ACommands()
            ack_command.acks.append(seqnum_to_ack)
            self.message_queue.put(ack_command)
            logger.debug(f"Queued immediate ACK for seqnum {seqnum_to_ack}")
        except Exception as e:
            logger.error(f"Error queueing immediate ACK for seqnum {seqnum_to_ack}: {e}", exc_info=True)
    
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

            for ack_seqnum in response.acks:
                logger.info(f"Processing ACK received from world for seqnum: {ack_seqnum}")
                self.process_ack(ack_seqnum) 

            for package in response.arrived:
                self._queue_ack_immediately(package.seqnum)
                self.process_arrived(package) 


            for package in response.ready:
                self._queue_ack_immediately(package.seqnum)
                self.process_ready(package)

            for package in response.loaded:
                logger.info("Receive Loaded Info, Processing package loaded...")
                self._queue_ack_immediately(package.seqnum)
                self.process_loaded(package) 

            for package in response.packagestatus:
                self._queue_ack_immediately(package.seqnum)
                self.process_package_status(package) 

            for error in response.error:
                self._queue_ack_immediately(error.seqnum)
                self.process_error(error)

            # with self.lock:
            #      self.acks.update(acks_to_send)

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
            # Create a new WorldMessage record for this ack
            try:
                new_message = WorldMessage(
                    seqnum=seqnum,
                    message_type='auto_created',
                    message_content=f"Auto-created record for ack {seqnum}",
                    status='acked'
                )
                db.session.add(new_message)
                db.session.commit()
                logger.info(f"Created new WorldMessage record for previously unknown seqnum {seqnum}")
            except Exception as create_err:
                db.session.rollback()
                logger.error(f"Failed to create WorldMessage for seqnum {seqnum}: {create_err}", exc_info=True)
                
        with self.lock:
            if seqnum in self.response_events:
                if seqnum not in self.pending_responses or self.pending_responses[seqnum] is None:
                    self.pending_responses[seqnum] = "ACK"
                self.response_events[seqnum].set()
                logger.info(f"Set event for seqnum {seqnum}")
            else:
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
        
        # with self.lock:
        #     self.acks.add(package.seqnum)
    
    def process_ready(self, package):
        logger.info(f"Package {package.shipid} is ready")
        from app.services.world_event_handler import WorldEventHandler

        handler = WorldEventHandler(self.app)
        handler.handle_world_event('package_ready', {
            'shipment_id': package.shipid
        })
        # with self.lock:
        #     self.acks.add(package.seqnum)
    
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
        
        # with self.lock:
        #     self.acks.add(package.seqnum)
    
    def process_package_status(self, package):
        logger.info(f"Package {package.packageid} status: {package.status}")
        
        with self.lock:
            if package.seqnum in self.response_events:
                self.pending_responses[package.seqnum] = package.status
                self.response_events[package.seqnum].set()
        
        # with self.lock:
        #     self.acks.add(package.seqnum)
    
    def process_error(self, error):
        logger.error(f"Error from world simulator: {error.err} (seqnum: {error.originseqnum})")
        
        # Store the error
        with self.lock:
            if error.originseqnum in self.response_events:
                self.pending_responses[error.originseqnum] = f"Error: {error.err}"
                self.response_events[error.originseqnum].set()
        
        # with self.lock:
        #     self.acks.add(error.seqnum)
    
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
            
            
            db.session.commit()
            logger.info(f"Cleaned up {deleted_count} old world messages")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error cleaning up world messages: {e}")

    def connect(self, world_id=None, init_warehouses=None):
        try:
            self.cleanup_old_world_messages()
            logger.info(f"Connecting to World Simulator at {self.host}:{self.port}...")
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect(('docker_deploy-server-1', self.port))
            logger.info("Connected to World Simulator")

            connect_msg = amazon_pb2.AConnect()
            connect_msg.isAmazon = True

            if world_id:
                connect_msg.worldid = world_id
            
            default_init_warehouses = []
            for i in range(1, 50):
                one_warehouse = Warehouse()
                one_warehouse.warehouse_id = i
                one_warehouse.x = random.randint(10, 100)
                one_warehouse.y = random.randint(10, 100)
                default_init_warehouses.append(one_warehouse)
                new_wh = connect_msg.initwh.add()
                new_wh.id = one_warehouse.warehouse_id
                new_wh.x = one_warehouse.x
                new_wh.y = one_warehouse.y
            
            if not init_warehouses:
                init_warehouses = default_init_warehouses
            else:
                for wh in init_warehouses:
                    new_wh = connect_msg.initwh.add()
                    new_wh.id = wh.warehouse_id
                    new_wh.x = wh.x
                    new_wh.y = wh.y

            self.send_protobuf(connect_msg)

            data = self.receive_message()
            response = amazon_pb2.AConnected()
            response.ParseFromString(data)

            self.world_id = response.worldid
            self.connected = response.result == "connected!"

            if not self.connected:
                logger.error(f"Failed to connect to World Simulator: {response.result}")
                self.socket.close()
                self.socket = None
                return None, response.result

            if init_warehouses:
                with self.app.app_context():
                    # db.session.query(Warehouse).filter_by(world_id=self.world_id).delete()
                    # db.session.commit()
                    logger.info(f"Skipping deletion of warehouses for world {self.world_id} during connect/init.")
                    for wh_data in init_warehouses:
                        existing_wh = db.session.get(Warehouse, wh_data.warehouse_id)
                        if existing_wh and existing_wh.world_id != self.world_id:
                            logger.warning(f"Warehouse ID {wh_data.warehouse_id} exists with a different world ID. Overwriting.")
                            db.session.delete(existing_wh)
                            db.session.commit()

                        new_db_wh = Warehouse(
                            warehouse_id=wh_data.warehouse_id,
                            x=wh_data.x,
                            y=wh_data.y,
                            world_id=self.world_id,
                            active=True
                        )
                        db.session.merge(new_db_wh)
                    try:
                        db.session.commit()
                        logger.info(f"Initialized/Updated {len(init_warehouses)} warehouses in DB for world {self.world_id}.")
                    except Exception as db_err:
                        db.session.rollback()
                        logger.error(f"Database error initializing warehouses: {db_err}", exc_info=True)
                        self.disconnect()
                        return None, f"DB init error: {db_err}"

            self.receiver_thread = threading.Thread(target=self.receive_loop)
            self.receiver_thread.daemon = True
            self.receiver_thread.start()

            self.sender_thread = threading.Thread(target=self._send_loop)
            self.sender_thread.daemon = True
            self.sender_thread.start()

            logger.info(f"Connected to World Simulator with world_id {self.world_id}. Starting product initialization...")

            try:
                with self.app.app_context():
                    target_warehouse_id = None
                    warehouse_list_for_init = init_warehouses if init_warehouses else []

                    if warehouse_list_for_init:
                        target_warehouse_id = warehouse_list_for_init[0].warehouse_id
                        logger.info(f"Using first initialized warehouse ({target_warehouse_id}) for product stocking.")
                    else:
                        first_warehouse = db.session.query(Warehouse).filter_by(world_id=self.world_id, active=True).first()
                        if first_warehouse:
                            target_warehouse_id = first_warehouse.warehouse_id
                            logger.info(f"Using first available warehouse ({target_warehouse_id}) from DB for product stocking.")
                        else:
                            logger.warning(f"Could not find an active warehouse for world {self.world_id} in DB. Trying default WH ID 1.")
                            default_wh = db.session.get(Warehouse, 1)
                            if default_wh and default_wh.active:
                                target_warehouse_id = 1
                                if default_wh.world_id != self.world_id:
                                    logger.info(f"Assigning world ID {self.world_id} to default warehouse 1.")
                                    default_wh.world_id = self.world_id
                                    db.session.commit()
                            else:
                                logger.error("Default warehouse ID 1 not found or inactive. Cannot initialize products.")
                    from app.model import Product
                    if target_warehouse_id is not None:
                        local_products = Product.query.all()
                        logger.info(f"Found {len(local_products)} products in local DB to potentially initialize in warehouse {target_warehouse_id}.")

                        products_initialized = 0
                        for product in local_products:
                            warehouse_stock = db.session.query(WarehouseProduct).filter_by(
                                warehouse_id=target_warehouse_id,
                                product_id=product.product_id
                            ).first()

                            initial_buy_quantity = 0
                            if warehouse_stock:
                                initial_buy_quantity = warehouse_stock.quantity
                                logger.debug(f"Product ID {product.product_id}: Found stock {initial_buy_quantity} in local DB for WH {target_warehouse_id}.")
                            else:
                                logger.warning(f"Product ID {product.product_id}: No stock record found in local DB for WH {target_warehouse_id}. Buying quantity 0.")

                            if initial_buy_quantity > 0:
                                logger.debug(f"Initializing product ID {product.product_id} ('{product.product_name}') with quantity {initial_buy_quantity} in WH {target_warehouse_id}")
                                self.buy_product(
                                    warehouse_id=target_warehouse_id,
                                    product_id=product.product_id,
                                    description=product.product_name,
                                    quantity=initial_buy_quantity
                                )
                                products_initialized += 1
                            else:
                                logger.debug(f"Skipping buy command for Product ID {product.product_id} as local quantity is 0 or less.")
                            # time.sleep(0.05) # Optional delay

                        logger.info(f"Sent initial buy commands for {products_initialized} products (with qty > 0) to warehouse {target_warehouse_id}.")
                    else:
                        logger.error("No target warehouse ID determined. Skipping product initialization.")

            except Exception as init_err:
                logger.error(f"Error during product initialization after connecting: {init_err}", exc_info=True)
                # self.disconnect()
                # return None, f"Product init error: {init_err}"

            default_speed_command = amazon_pb2.ACommands()
            default_speed_command.simspeed = self.app.config.get('DEFAULT_SIM_SPEED', 1000)
            self.queue_command(default_speed_command)
            logger.info(f"Queued command to set sim speed to {default_speed_command.simspeed}")

            logger.info(f"Connection process complete for world_id {self.world_id}")
            return self.world_id, response.result

        except ConnectionRefusedError:
            logger.error(f"Connection refused by World Simulator at {self.host}:{self.port}.")
            self.socket = None
            return None, "Connection refused"
        except socket.timeout:
            logger.error(f"Connection timed out to World Simulator at {self.host}:{self.port}.")
            self.socket = None
            return None, "Connection timed out"
        except Exception as e:
            logger.error(f"Error connecting to World Simulator: {e}", exc_info=True)
            if self.socket:
                try:
                    self.socket.close()
                except Exception:
                    pass
            self.socket = None
            self.connected = False
            return None, str(e)

    def query_package(self, package_id):
        if not self.connected:
            return False, "Not connected to World Simulator"


        try:
            command = amazon_pb2.ACommands()
            query = command.queries.add()
            query.packageid = package_id # This is the shipment_id
            query.seqnum = self._get_next_seqnum()

            # Log the command being sent
            with self.app.app_context(): # Use context for DB operation
                db_message = WorldMessage(
                    seqnum=query.seqnum,
                    message_type='query',
                    message_content=f"Query Package ID: {package_id}",
                    status='sent'
                )
                db.session.add(db_message)
                db.session.commit()


            # Prepare to wait for the response
            event = threading.Event()
            with self.lock:
                self.response_events[query.seqnum] = event

            self.queue_command(command)
            logger.info(f"Queued query command for package ID {package_id} (seqnum: {query.seqnum})")

            # Wait for the response or timeout
            if event.wait(timeout=10): # Adjust timeout if needed
                with self.lock:
                    if query.seqnum in self.pending_responses:
                        response_status = self.pending_responses[query.seqnum]
                        logger.info(f"Received response for query seqnum {query.seqnum}: Status='{response_status}'")
                        # Clean up
                        del self.pending_responses[query.seqnum]
                        if query.seqnum in self.response_events: del self.response_events[query.seqnum]
                        # The response is likely the status string (e.g., "packed", "loaded")
                        return True, response_status
                    else:
                        # Event was set, but no response recorded? Should ideally not happen with current logic.
                        logger.warning(f"Event set for query seqnum {query.seqnum}, but no response found in pending_responses.")
                        return False, "Response event triggered, but data missing"
            else:
                logger.warning(f"Timeout waiting for query response for package ID {package_id} (seqnum: {query.seqnum})")
                # Clean up the event waiter if timed out
                with self.lock:
                    if query.seqnum in self.response_events:
                        del self.response_events[query.seqnum]
                    # Optionally remove from pending_responses too if it might get populated later erroneously
                    if query.seqnum in self.pending_responses:
                        del self.pending_responses[query.seqnum]
                return False, "Timeout waiting for query response"

        # except ConnectionResetError:
        except Exception as e:
            logger.error(f"Error querying package {package_id}: {e}", exc_info=True)
            with self.app.app_context():
                db.session.rollback()
            with self.lock:
                 if 'query' in locals() and query.seqnum in self.response_events:
                     del self.response_events[query.seqnum]
                 if 'query' in locals() and query.seqnum in self.pending_responses:
                      del self.pending_responses[query.seqnum]
            return False, str(e)

