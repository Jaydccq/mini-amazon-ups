import socket
import threading
import time
import struct
import logging
import queue
from datetime import datetime
from google.protobuf.message import Message

from model import db, WorldMessage, Warehouse
from proto import world_amazon_1_pb2 as amazon_pb2

logger = logging.getLogger(__name__)

class WorldSimulatorService:
    def __init__(self, host='world-simulator', port=23456):
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
        
        self._load_last_seqnum()
    
    # Load the last used sequence number 
    def _load_last_seqnum(self):
        last_message = WorldMessage.query.order_by(WorldMessage.seqnum.desc()).first()
        if last_message:
            with self.lock:
                self.seqnum = last_message.seqnum

    # Get the next sequence number    
    def _get_next_seqnum(self):
        with self.lock:
            self.seqnum += 1
            return self.seqnum
    
    # Connect to the world simulator
    def connect(self, world_id=None, init_warehouses=None):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            
            # Create connection message
            connect_msg = amazon_pb2.AConnect()
            connect_msg.isAmazon = True
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
                
                logger.info("Disconnected from World Simulator")
        except Exception as e:
            logger.error(f"Error disconnecting from World Simulator: {e}")
    
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
            product.description = description
            product.count = quantity
            
            db_message = WorldMessage(
                seqnum=buy.seqnum,
                message_type='buy',
                message_content=f"Warehouse: {warehouse_id}, Product: {product_id}, Quantity: {quantity}",
                status='sent'
            )
            db.session.add(db_message)
            db.session.commit()
            
            event = threading.Event()
            with self.lock:
                self.response_events[buy.seqnum] = event
            
            # Queue the command
            self.queue_command(command)
            
            if event.wait(timeout=10):
                with self.lock:
                    if buy.seqnum in self.pending_responses:
                        response = self.pending_responses[buy.seqnum]
                        del self.pending_responses[buy.seqnum]
                        del self.response_events[buy.seqnum]
                        return True, response
                    
            return False, "Timeout waiting for response"
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
        while self.running:
            try:
                # Receive response
                data = self.receive_message()
                if not data:
                    logger.warning("Empty response received")
                    continue
                
                # Parse response
                response = amazon_pb2.AResponses()
                response.ParseFromString(data)
                
                # Process response
                self.process_response(response)
            except Exception as e:
                logger.error(f"Error in receive loop: {e}")
                time.sleep(1)  
    
    def process_response(self, response):
        try:
            for ack in response.acks:
                self.process_ack(ack)
            
            for package in response.arrived:
                self.process_arrived(package)
            
            for package in response.ready:
                self.process_ready(package)
            
            for package in response.loaded:
                self.process_loaded(package)
            
            for package in response.packagestatus:
                self.process_package_status(package)
            
            for error in response.error:
                self.process_error(error)
            
            with self.lock:
                self.acks.add(response.seqnum)
        except Exception as e:
            logger.error(f"Error processing response: {e}")
    
    def process_ack(self, seqnum):
        logger.debug(f"Received ack for seqnum {seqnum}")
        message = WorldMessage.query.filter_by(seqnum=seqnum).first()
        if message:
            message.status = 'acked'
            db.session.commit()
        
        with self.lock:
            if seqnum in self.response_events:
                self.pending_responses[seqnum] = "ACK"
                self.response_events[seqnum].set()
    
    def process_arrived(self, package):
        logger.info(f"Products arrived for warehouse {package.whnum}")
        from app.services.world_event_handler import WorldEventHandler
        handler = WorldEventHandler()
        
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
        handler = WorldEventHandler()
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
            handler = WorldEventHandler()
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
        serialized = message.SerializeToString()
        # Send message size as 4-byte integer
        self.socket.sendall(struct.pack("!I", len(serialized)))
        # Send the message
        self.socket.sendall(serialized)
    
    # receive a message
    def receive_message(self):
        # Receive message size (4 bytes)
        size_data = self.recvall(4)
        if not size_data:
            return None
        
        # Unpack message size
        message_size = struct.unpack("!I", size_data)[0]
        
        # Receive message data
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
    
    # Add to world_simulator_service.py
    def _reconnect_with_backoff(self):
        """Reconnect to world simulator with exponential backoff"""
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