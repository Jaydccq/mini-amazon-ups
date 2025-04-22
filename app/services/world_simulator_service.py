import socket
import threading
import time
import struct
import logging
import queue
from datetime import datetime
from google.protobuf.message import Message

from model import db, WorldMessage, Warehouse
from proto import amazon_pb2

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
        
        # Load last used sequence number from database
        self._load_last_seqnum()
    
    def _load_last_seqnum(self):
        """Load the last used sequence number from database"""
        last_message = WorldMessage.query.order_by(WorldMessage.seqnum.desc()).first()
        if last_message:
            with self.lock:
                self.seqnum = last_message.seqnum
    
    def _get_next_seqnum(self):
        """Get the next sequence number"""
        with self.lock:
            self.seqnum += 1
            return self.seqnum
    
    def connect(self, world_id=None, init_warehouses=None):
        """Connect to the world simulator"""
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
            self._send_protobuf(connect_msg)
            
            # Receive response
            data = self._receive_message()
            response = amazon_pb2.AConnected()
            response.ParseFromString(data)
            
            self.world_id = response.worldid
            self.connected = response.result == "connected!"
            
            if not self.connected:
                logger.error(f"Failed to connect to World Simulator: {response.result}")
                return None, response.result
            
            # Start background threads
            self.receiver_thread = threading.Thread(target=self._receive_loop)
            self.receiver_thread.daemon = True
            self.receiver_thread.start()
            
            self.sender_thread = threading.Thread(target=self._send_loop)
            self.sender_thread.daemon = True
            self.sender_thread.start()
            
            logger.info(f"Connected to World Simulator with world_id {self.world_id}")
            
            return self.world_id, response.result
        except Exception as e:
            logger.error(f"Error connecting to World Simulator: {e}")
            return None, str(e)
    
    def disconnect(self):
        """Disconnect from the world simulator"""
        try:
            if self.connected:
                # Send disconnect command
                command = amazon_pb2.ACommands()
                command.disconnect = True
                self._queue_command(command)
                
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
        """Purchase more products for a warehouse"""
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
            
            # Save command to database
            db_message = WorldMessage(
                seqnum=buy.seqnum,
                message_type='buy',
                message_content=f"Warehouse: {warehouse_id}, Product: {product_id}, Quantity: {quantity}",
                status='sent'
            )
            db.session.add(db_message)
            db.session.commit()
            
            # Create event for this sequence number
            event = threading.Event()
            with self.lock:
                self.response_events[buy.seqnum] = event
            
            # Queue the command
            self._queue_command(command)
            
            # Wait for response
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
        """Request packing of a shipment"""
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
            
            # Save command to database
            db_message = WorldMessage(
                seqnum=pack.seqnum,
                message_type='topack',
                message_content=f"Warehouse: {warehouse_id}, Shipment: {shipment_id}, Items: {len(items)}",
                status='sent'
            )
            db.session.add(db_message)
            db.session.commit()
            
            # Create event for this sequence number
            event = threading.Event()
            with self.lock:
                self.response_events[pack.seqnum] = event
            
            # Queue the command
            self._queue_command(command)
            
            # Wait for response
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
        """Request loading a shipment onto a truck"""
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
            
            # Create event for this sequence number
            event = threading.Event()
            with self.lock:
                self.response_events[load.seqnum] = event
            
            # Queue the command
            self._queue_command(command)
            
            # Wait for response
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
        """Query the status of a package"""
        if not self.connected:
            return False, "Not connected to World Simulator"
        
        try:
            command = amazon_pb2.ACommands()
            query = command.queries.add()
            query.packageid = package_id
            query.seqnum = self._get_next_seqnum()
            
            # Save command to database
            db_message = WorldMessage(
                seqnum=query.seqnum,
                message_type='query',
                message_content=f"Package: {package_id}",
                status='sent'
            )
            db.session.add(db_message)
            db.session.commit()
            
            # Create event for this sequence number
            event = threading.Event()
            with self.lock:
                self.response_events[query.seqnum] = event
            
            # Queue the command
            self._queue_command(command)
            
            # Wait for response
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
    
    def _queue_command(self, command):
        """Add pending acks to command and queue it for sending"""
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
                self._send_protobuf(command)
                
                # Mark as done
                self.message_queue.task_done()
            except Exception as e:
                logger.error(f"Error in send loop: {e}")
                time.sleep(1)  # Avoid tight loop on error
    
    def _receive_loop(self):
        """Background thread for receiving responses"""
        while self.running:
            try:
                # Receive response
                data = self._receive_message()
                if not data:
                    logger.warning("Empty response received")
                    continue
                
                # Parse response
                response = amazon_pb2.AResponses()
                response.ParseFromString(data)
                
                # Process response
                self._process_response(response)
            except Exception as e:
                logger.error(f"Error in receive loop: {e}")
                time.sleep(1)  # Avoid tight loop on error
    
    def _process_response(self, response):
        """Process a response from the world simulator"""
        try:
            # Process acknowledgments
            for ack in response.acks:
                self._process_ack(ack)
            
            # Process arrived products
            for package in response.arrived:
                self._process_arrived(package)
            
            # Process ready packages
            for package in response.ready:
                self._process_ready(package)
            
            # Process loaded packages
            for package in response.loaded:
                self._process_loaded(package)
            
            # Process package status responses
            for package in response.packagestatus:
                self._process_package_status(package)
            
            # Process errors
            for error in response.error:
                self._process_error(error)
            
            # Add to pending acks
            with self.lock:
                self.acks.add(response.seqnum)
        except Exception as e:
            logger.error(f"Error processing response: {e}")
    
    def _process_ack(self, seqnum):
        """Process acknowledgment from world simulator"""
        logger.debug(f"Received ack for seqnum {seqnum}")
        
        # Update message status in database
        message = WorldMessage.query.filter_by(seqnum=seqnum).first()
        if message:
            message.status = 'acked'
            db.session.commit()
        
        # Set event to notify waiting threads
        with self.lock:
            if seqnum in self.response_events:
                self.pending_responses[seqnum] = "ACK"
                self.response_events[seqnum].set()
    
    def _process_arrived(self, package):
        """Process arrived products notification"""
        logger.info(f"Products arrived for warehouse {package.whnum}")
        
        # Handle the product arrival through the event handler
        from app.services.world_event_handler import WorldEventHandler
        handler = WorldEventHandler()
        
        for product in package.things:
            handler.handle_world_event('product_arrived', {
                'warehouse_id': package.whnum,
                'product_id': product.id,
                'description': product.description,
                'quantity': product.count
            })
        
        # Notify world that we've received this message
        with self.lock:
            self.acks.add(package.seqnum)
    
    def _process_ready(self, package):
        """Process ready package notification"""
        logger.info(f"Package {package.shipid} is ready")
        
        # Handle the package ready event through the event handler
        from app.services.world_event_handler import WorldEventHandler
        handler = WorldEventHandler()
        handler.handle_world_event('package_ready', {
            'shipment_id': package.shipid
        })
        
        # Notify world that we've received this message
        with self.lock:
            self.acks.add(package.seqnum)
    
    def _process_loaded(self, package):
        """Process loaded package notification"""
        logger.info(f"Package {package.shipid} is loaded")
        
        # Get the shipment to find out which truck it was loaded on
        from app.model import Shipment
        shipment = Shipment.query.filter_by(shipment_id=package.shipid).first()
        
        if shipment and shipment.truck_id:
            # Handle the package loaded event through the event handler
            from app.services.world_event_handler import WorldEventHandler
            handler = WorldEventHandler()
            handler.handle_world_event('package_loaded', {
                'shipment_id': package.shipid,
                'truck_id': shipment.truck_id
            })
        
        # Notify world that we've received this message
        with self.lock:
            self.acks.add(package.seqnum)
    
    def _process_package_status(self, package):
        """Process package status response"""
        logger.info(f"Package {package.packageid} status: {package.status}")
        
        # Store the status in the pending responses
        with self.lock:
            if package.seqnum in self.response_events:
                self.pending_responses[package.seqnum] = package.status
                self.response_events[package.seqnum].set()
        
        # Notify world that we've received this message
        with self.lock:
            self.acks.add(package.seqnum)
    
    def _process_error(self, error):
        """Process error response"""
        logger.error(f"Error from world simulator: {error.err} (seqnum: {error.originseqnum})")
        
        # Store the error in the pending responses
        with self.lock:
            if error.originseqnum in self.response_events:
                self.pending_responses[error.originseqnum] = f"Error: {error.err}"
                self.response_events[error.originseqnum].set()
        
        # Notify world that we've received this message
        with self.lock:
            self.acks.add(error.seqnum)
    
    def _send_protobuf(self, message):
        """Send a Protocol Buffer message"""
        serialized = message.SerializeToString()
        # Send message size as 4-byte integer
        self.socket.sendall(struct.pack("!I", len(serialized)))
        # Send the message
        self.socket.sendall(serialized)
    
    def _receive_message(self):
        """Receive a message from the socket"""
        # Receive message size (4 bytes)
        size_data = self._recvall(4)
        if not size_data:
            return None
        
        # Unpack message size
        message_size = struct.unpack("!I", size_data)[0]
        
        # Receive message data
        return self._recvall(message_size)
    
    def _recvall(self, n):
        """Receive exactly n bytes"""
        data = b''
        while len(data) < n:
            packet = self.socket.recv(n - len(data))
            if not packet:
                return None
            data += packet
        return data