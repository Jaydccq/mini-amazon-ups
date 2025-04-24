import sys
import os
import time
import logging
from flask import Flask

# --------------------------
# 1. Application setup
# --------------------------
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, '.'))
sys.path.append(project_root)

# Create Flask app and push context for SQLAlchemy
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL',
    'postgresql://postgres:abc123@localhost:5432/mini_amazon'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Make sure to import db and Warehouse *after* app is created if they rely on app context implicitly
# or ensure db is initialized correctly before models are defined/imported.
# Assuming model definitions are safe to import here:
from app.model import db, Warehouse
from app.services.world_simulator_service import WorldSimulatorService

db.init_app(app)
# Push global context if needed by setup_test_env or other setup steps
tx = app.app_context()
tx.push()

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --------------------------
# 2. Setup test DB record
# --------------------------
def setup_test_env():
    """
    Ensure a warehouse exists for testing. Needs app context.
    """
    try:
        logger.info("Checking for test Warehouse (ID=1)...")
        # Use db.session.get which is preferred for fetching by primary key
        w = db.session.get(Warehouse, 1)
        if not w:
            w = Warehouse(warehouse_id=1, x=10, y=10, active=True)
            db.session.add(w)
            db.session.commit()
            logger.info("Created test Warehouse ID=1")
        else:
            logger.info("Test Warehouse already present")
    except Exception as e:
        logger.error(f"setup_test_env error: {e}", exc_info=True) # Log traceback
        db.session.rollback() # Rollback on error
        raise

# --------------------------
# 3. World Simulator tests
# --------------------------
def main():
    # Setup needs the global context pushed earlier
    setup_test_env()

    # --- START FIX ---
    # Fetch the warehouse(s) to initialize in the simulator
    # This also needs the global context pushed earlier or its own context
    initial_warehouses = []
    try:
        # Fetch the specific warehouse used in tests
        test_warehouse = db.session.get(Warehouse, 1)
        if test_warehouse:
            initial_warehouses.append(test_warehouse)
            logger.info(f"Fetched Warehouse ID=1 (Coords: {test_warehouse.x},{test_warehouse.y}) for simulator init.")
        else:
             logger.error("Test warehouse ID=1 not found in database after setup! Cannot connect to world.")
             return # Cannot proceed without the warehouse
    except Exception as e:
        logger.error(f"Error fetching warehouse for init: {e}", exc_info=True)
        return
    # --- END FIX ---

    host = os.environ.get('WORLD_HOST', 'localhost')
    port = int(os.environ.get('WORLD_PORT', '23456'))
    logger.info(f"Connecting to World Simulator at {host}:{port}...")

    # Pass app object to the service
    service = WorldSimulatorService(app=app, host=host, port=port)

    # Pass the fetched warehouses to connect method
    world_id, result = service.connect(init_warehouses=initial_warehouses)

    if world_id is None or isinstance(result, Exception):
        logger.error(f"Connect failed: {result}")
        return
    logger.info(f"Connected (world_id={world_id})")

    # Speed up simulation so responses arrive quickly
    try:
        # Send commands within an app context as they interact with DB
        with app.app_context():
            service.set_sim_speed(1000) # Assuming set_sim_speed might interact with DB or needs context
        logger.info("Simulation speed set to 1000")
    except Exception as e:
        logger.warning(f"set_sim_speed failed or not supported; proceeding without speed change. Error: {e}")

    # 3.1 Buy product
    logger.info("--- Test: buy_product ---")
    # Use context for DB interaction within buy_product
    with app.app_context():
        success, resp = service.buy_product(
            warehouse_id=1,
            product_id=101, # Make sure product 101 definition is consistent if it exists
            description="TestItem",
            quantity=5
        )
    logger.info(f"buy_product -> success={success}, resp={resp}")
    # Allow time for processing and potential arrival message
    time.sleep(10) # Might need adjustment based on sim speed

    # 3.2 Pack shipment
    shipment_id = int(time.time()) # Use a potentially unique ID
    logger.info("--- Test: pack_shipment ---")
     # Use context for DB interaction within pack_shipment
    with app.app_context():
        success, resp = service.pack_shipment(
            warehouse_id=1,
            shipment_id=shipment_id,
            items=[{"product_id":101, "description":"TestItem", "quantity":1}] # Ensure product 101 exists or was bought
        )
    logger.info(f"pack_shipment -> success={success}, resp={resp}")
    # Allow time for packing and ready message
    time.sleep(15) # Might need adjustment

    # 3.3 Query package status
    logger.info("--- Test: query_package ---")
     # Use context for DB interaction within query_package
    with app.app_context():
        success, status = service.query_package(package_id=shipment_id)
    logger.info(f"query_package -> success={success}, status={status}")
    time.sleep(5) # Allow time for query response

    # Disconnect
    logger.info("Disconnecting...")
    # disconnect might implicitly need context if it joins threads that use it
    with app.app_context():
        service.disconnect()
    logger.info("Done")

if __name__ == '__main__':
    try:
        main()
    finally:
        # Pop context only after main finishes or raises exception
        if tx:
           try:
               tx.pop()
               logger.info("Popped global application context.")
           except RuntimeError as e:
               # Handle cases where context might have been popped elsewhere or never pushed properly
               logger.warning(f"Could not pop application context: {e}")
           except Exception as e:
                logger.error(f"Unexpected error popping context: {e}", exc_info=True)