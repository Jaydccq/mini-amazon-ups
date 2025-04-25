import sys
import os
import time
import logging
import threading # Needed for Event
from flask import Flask
# Import necessary models for app context and potentially checking warehouse
from app.model import db, Warehouse
# Import WorldSimulatorService
from app.services.world_simulator_service import WorldSimulatorService

script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, '.'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL',
    'postgresql://postgres:abc123@db:5432/mini_amazon'
)
# Disable SQLAlchemy event system, saves resources
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Add a secret key for session management if needed by extensions
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a-default-test-secret-key')

# Initialize the database extension with the app
db.init_app(app)

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)


# --------------------------------------
# 2. World Simulator Connection Logic
# --------------------------------------
def initialize_and_connect():
    """Connects to the simulator and returns the service instance."""
    # Optional: Check if warehouse 1 exists, but not strictly necessary for connection test
    try:
        with app.app_context():
            test_warehouse = db.session.get(Warehouse, 1)
            if test_warehouse:
                logger.debug(f"Checked Warehouse ID=1 exists (Coords: {test_warehouse.x},{test_warehouse.y}).")
            else:
                # You might want to ensure it exists if the simulator *requires* a warehouse even for connection.
                # Otherwise, just warn.
                logger.warning("Test warehouse ID=1 not found in database. Proceeding with connection attempt.")
    except Exception as e:
        logger.error(f"Error checking warehouse: {e}", exc_info=True)
        # Continue connection attempt even if DB check fails? Or return None? For connection test, let's try anyway.
        # return None

    # Get World Simulator host and port from environment variables or use defaults
    host = os.environ.get('WORLD_HOST', 'server') # Default changed to match docker-compose
    port = int(os.environ.get('WORLD_PORT', '23456')) # Amazon connection port
    logger.info(f"Attempting connection to World Simulator at {host}:{port}...")

    # Create WorldSimulatorService instance, passing the Flask app object
    service = WorldSimulatorService(app=app, host=host, port=port)

    # --- Connect to World Simulator ---
    # Attempt to connect to an existing world ID=1 (or change if needed)
    existing_world_id = 1
    logger.info(f"Attempting to connect to existing world ID: {existing_world_id}")
    # Pass init_warehouses=None because we connect to an existing world
    world_id, result = service.connect(world_id=existing_world_id, init_warehouses=None)

    if world_id is None or not result == "connected!":
        # Check if connection failed
        logger.error(f"Connection failed: {result}")
        return None, None # Return None for service if connection fails
    logger.info(f"Successfully connected! (World ID: {world_id}), Result: {result}")

    return service, world_id

# --------------------------
# 3. Main Execution Logic
# --------------------------
if __name__ == '__main__':
    logger.info("--- Starting World Simulator Connection Test ---")
    # Need app context to potentially check DB during initialize_and_connect
    with app.app_context():
        world_service, connected_world_id = initialize_and_connect()

        if world_service and world_service.connected:
            print("\n-----------------------------------------")
            print(f"Successfully connected to World ID: {connected_world_id}")
            print("Connection test passed.")
            print("-----------------------------------------\n")
            print("Connection is active. Press Ctrl+C to disconnect and exit.")
            try:
                 # Keep the script running while the service is active
                 while world_service.running:
                      time.sleep(1)
            except KeyboardInterrupt:
                 print("\nDisconnecting due to user interruption...")
            finally:
                 # Ensure disconnection happens even if loop exits unexpectedly
                 if world_service and world_service.connected:
                      world_service.disconnect()
                      print("Disconnected from World Simulator.")
        else:
            print("\n-----------------------------------------")
            print("Failed to connect to the World Simulator.")
            print("Connection test failed.")
            print("-----------------------------------------\n")

    logger.info("--- Connection Test Script Finished ---")