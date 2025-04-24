import sys
import os
import time
import logging
import threading # Needed for Event
from flask import Flask
from app.model import db, Warehouse, Product, ProductCategory, User, Shipment, OrderProduct # Import necessary models including User and ProductCategory
# Removed direct import of SQLAlchemy here as db is initialized later
# from flask_sqlalchemy import SQLAlchemy

# --------------------------
# 1. Application setup
# --------------------------
# Get the directory of the current script and the project root
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, '.'))
# Add the project root to the Python path to allow importing 'app' modules
sys.path.append(project_root)

# Create Flask app instance
app = Flask(__name__)
# Configure database URI, getting from environment variable or using a default
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL',
    'postgresql://postgres:abc123@localhost:5432/mini_amazon'
)
# Disable SQLAlchemy event system, saves resources
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Add a secret key for session management if needed by extensions
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a-default-test-secret-key')

# Import database object (db) and models *after* app creation
# Use try-except for robustness if imports might fail
try:
    from app.model import db, Warehouse, Product, Shipment, OrderProduct # Import necessary models
    from app.services.world_simulator_service import WorldSimulatorService
    # from app.services.shipment_service import ShipmentService # Might be useful for status checks
except ImportError as e:
     print(f"Error importing application modules: {e}")
     print("Ensure the script is run from the project root or the path is correctly set.")
     sys.exit(1)


# Initialize the database extension with the app
db.init_app(app)
# Push an application context globally. This is necessary for SQLAlchemy operations
# outside of a normal Flask request context (e.g., in setup_test_env or service methods).
# NOTE: Using a global context like this is generally discouraged in larger apps.
# Consider using `with app.app_context():` blocks within functions instead.
# For this script, we'll keep it for simplicity, but be aware of potential issues.
tx = app.app_context()
tx.push()

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)

# --------------------------
# 2. Setup test DB record
# --------------------------
def setup_test_env():
    """
    Ensure a warehouse (ID=1) exists in the database for testing.
    Requires application context for database operations.
    """
    # No need for manual app_context() push/pop here as tx is globally pushed
    try:
        logger.info("Checking for test Warehouse (ID=1)...")
        # Use db.session.get to fetch by primary key (preferred)
        w = db.session.get(Warehouse, 1)
        if not w:
            # If warehouse doesn't exist, create it
            w = Warehouse(warehouse_id=1, x=10, y=10, active=True)
            db.session.add(w)
            db.session.commit() # Commit the transaction to save to DB
            logger.info("Created test Warehouse ID=1 (Coords: 10, 10)")
        else:
            # If warehouse already exists
            logger.info(f"Test Warehouse ID=1 already present (Coords: {w.x}, {w.y})")

        # Ensure the product we want to buy exists for testing inventory checks later
        test_prod = db.session.get(Product, 101)
        if not test_prod:
             # Find an existing seller or create one if needed
             seller = db.session.query(User).filter_by(is_seller=True).first()
             if not seller:
                  logger.warning("No seller found, creating dummy seller admin@example.com if not exists")
                  # Assuming admin user from create_database.sql or __init__.py exists
                  seller = db.session.query(User).filter_by(email='admin@example.com').first()
                  if not seller: # If admin still not found, create a basic one (adjust as needed)
                       seller = User(email='test_seller@example.com', first_name='Test', last_name='Seller', is_seller=True)
                       seller.set_password('password')
                       db.session.add(seller)
                       db.session.commit()
                       logger.info("Created basic test seller.")

             # Find a category or create one
             category = db.session.query(ProductCategory).first()
             if not category:
                  category = ProductCategory(category_name='Test Category')
                  db.session.add(category)
                  db.session.commit()
                  logger.info("Created basic test category.")

             logger.info("Creating test Product ID=101 (TestItem)...")
             test_prod = Product(product_id=101, product_name="TestItem", description="Item for testing", price=9.99, owner_id=seller.user_id, category_id=category.category_id)
             db.session.add(test_prod)
             db.session.commit()
        else:
             logger.info("Test Product ID=101 already present.")


    except Exception as e:
        # Log detailed error and rollback transaction on failure
        logger.error(f"setup_test_env error: {e}", exc_info=True)
        db.session.rollback()
        raise # Re-raise the exception so the caller knows something went wrong

# --------------------------------------
# 3. World Simulator Service Integration
# (Initialize service and connect)
# --------------------------------------
def initialize_and_connect():
    """Initializes warehouses, connects to the simulator, and returns the service instance."""
    initial_warehouses = []
    try:
        # Fetch the specific warehouse used in tests (needs app context)
        test_warehouse = db.session.get(Warehouse, 1)
        if test_warehouse:
            initial_warehouses.append(test_warehouse)
            logger.info(f"Fetched Warehouse ID=1 (Coords: {test_warehouse.x},{test_warehouse.y}) for simulator init.")
        else:
             # If warehouse not found after setup, cannot proceed
             logger.error("Test warehouse ID=1 not found in database after setup! Cannot connect to world.")
             return None # Cannot proceed without the warehouse
    except Exception as e:
        logger.error(f"Error fetching warehouse for init: {e}", exc_info=True)
        return None

    # Get World Simulator host and port from environment variables or use defaults
    host = os.environ.get('WORLD_HOST', 'localhost') # Usually 'world-simulator' in docker-compose.yml
    port = int(os.environ.get('WORLD_PORT', '23456')) # Amazon connection port
    logger.info(f"Connecting to World Simulator at {host}:{port}...")

    # Create WorldSimulatorService instance, passing the Flask app object
    # Passing 'app' allows the service's background thread to create app contexts for DB operations
    service = WorldSimulatorService(app=app, host=host, port=port)

    # --- Connect to World Simulator ---
    # Call the connect method, passing the list of warehouses to initialize
    world_id, result = service.connect(init_warehouses=initial_warehouses)

    if world_id is None or not result == "connected!":
        # Check if connection failed
        logger.error(f"Connect failed: {result}")
        # service.disconnect() # Optional cleanup if connect fails partially
        return None # Cannot continue
    logger.info(f"Connected (world_id={world_id}), Result: {result}")

    # --- Set Simulation Speed (with Check) ---
    # Attempt to increase simulation speed for faster responses
    try:
        # Call within app context in case the method needs DB access or app config
        # (WorldSimulatorService methods already handle app context internally if 'app' was passed)
        sim_speed_set_locally = service.set_sim_speed(1000)

        if sim_speed_set_locally:
            logger.info("Simulation speed set command sent (1000).")
            # NOTE: World Sim doesn't explicitly ACK simspeed changes.
            # We assume it worked if the command was sent without error.
            # A more robust check could involve timing a known operation.
            # The server might ignore this command based on its configuration.
        else:
            logger.warning("Failed to queue simulation speed command (service disconnected or queue error?).")
    except Exception as e:
        # Catch potential exceptions (e.g., if World Sim doesn't support the command)
        logger.warning(f"set_sim_speed failed locally or not supported; proceeding without speed change. Error: {e}")

    return service, world_id


# --------------------------
# 4. Test Helper Functions
# --------------------------
def wait_for_shipment_status(shipment_id, target_status, service, timeout=30):
    """Polls the database for the shipment status until it reaches the target or timeout."""
    logger.info(f"Waiting for shipment {shipment_id} to reach status '{target_status}' (timeout: {timeout}s)...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        # Use app context for DB access within this helper
        with app.app_context():
            shipment = db.session.get(Shipment, shipment_id)
            if shipment and shipment.status == target_status:
                logger.info(f"Shipment {shipment_id} reached status '{target_status}'.")
                return True, shipment.status
            # Also check via query command if DB update is delayed
            query_success, current_status = service.query_package(package_id=shipment_id)
            if query_success and current_status == target_status:
                 logger.info(f"Shipment {shipment_id} reached status '{target_status}' (verified via query).")
                 return True, current_status

        time.sleep(2) # Check every 2 seconds
    logger.warning(f"Timeout waiting for shipment {shipment_id} to reach status '{target_status}'. Last seen status: {shipment.status if shipment else 'Not Found'}")
    return False, shipment.status if shipment else 'Not Found'

# --------------------------
# 5. Test Scenarios
# --------------------------

def test_full_flow(service, world_id):
    """Tests the basic BUY -> PACK -> LOAD -> DELIVER flow."""
    logger.info("--- Starting Test: Full Flow ---")
    warehouse_id = 1
    product_info = {"product_id": 101, "description": "TestItem", "quantity": 5}
    shipment_id = int(time.time()) # Unique ID for this test run

    # --- 5.1 Test: Buy Product ---
    logger.info(f"--- Test Step: buy_product (Product ID: {product_info['product_id']}) ---")
    success, resp = service.buy_product(
        warehouse_id=warehouse_id,
        product_id=product_info["product_id"],
        description=product_info["description"],
        quantity=product_info["quantity"]
    )
    logger.info(f"buy_product -> success={success}, response={resp}")
    assert success, f"buy_product command failed. Response: {resp}."
    # Wait for AArrived notification (implicitly handled by background thread)
    # We can verify by checking inventory later if needed, or add explicit wait/check
    logger.info("Waiting for product arrival notification (approx 10s)...")
    time.sleep(10) # Adjust based on sim speed

    # --- 5.2 Test: Pack Shipment ---
    items_to_pack = [{"product_id": product_info["product_id"], "description": product_info["description"], "quantity": 1}]
    logger.info(f"--- Test Step: pack_shipment (Shipment ID: {shipment_id}) ---")
    success, resp = service.pack_shipment(
        warehouse_id=warehouse_id,
        shipment_id=shipment_id,
        items=items_to_pack
    )
    logger.info(f"pack_shipment -> success={success}, response={resp}")
    assert success, f"pack_shipment command failed. Response: {resp}."
    # Wait for AReady notification and check status
    # The background thread in WorldSimulatorService should update DB status upon receiving AReady
    success, status = wait_for_shipment_status(shipment_id, 'packed', service, timeout=30)
    assert success, f"Shipment {shipment_id} did not reach 'packed' status. Final status: {status}"

    # --- 5.3 Simulate UPS Pickup ---
    # In a real system, AReady would trigger Amazon to notify UPS.
    # UPS would then send UGoPickup(whid=warehouse_id) to the World Simulator (UPS port).
    # World Simulator would send UFinished(status='arrive warehouse', truckid=X, x=WH_X, y=WH_Y) back to UPS.
    # UPS would notify Amazon via webhook (/api/ups/truck-arrived) with truck_id=X.
    # Amazon's webhook handler calls shipment_service.handle_truck_arrived(truck_id=X, warehouse_id=warehouse_id).
    # handle_truck_arrived updates DB status to 'loading' and calls Amazon's load_shipment.

    # ** MOCK / SIMULATION for this test **
    logger.info("--- Test Step: Simulating UPS Pickup ---")
    # Assume UPS sent pickup and truck 5 has arrived.
    mock_truck_id = 5
    logger.info(f"Simulating truck {mock_truck_id} arrival at warehouse {warehouse_id}.")
    # Manually trigger the logic that the webhook would trigger:
    # (Requires ShipmentService instance, or direct DB manipulation for test)
    try:
        with app.app_context(): # Ensure context for DB operations
             shipment = db.session.get(Shipment, shipment_id)
             if shipment and shipment.status == 'packed':
                  shipment.truck_id = mock_truck_id
                  # shipment.status = 'loading' # This status change should be done by load_shipment or its handler
                  db.session.commit()
                  logger.info(f"Updated Shipment {shipment_id} with truck_id {mock_truck_id}.")
             elif not shipment:
                  logger.error(f"Shipment {shipment_id} not found in DB for truck arrival simulation.")
                  assert False, "Shipment not found during mock truck arrival."
             else:
                  logger.warning(f"Shipment {shipment_id} status was '{shipment.status}', expected 'packed' for truck arrival.")
                  # Allow proceeding but log warning, load might fail if status is wrong.
    except Exception as e:
         logger.error(f"Error during mock truck arrival simulation: {e}", exc_info=True)
         assert False, "Mock truck arrival simulation failed."

    # --- 5.4 Test: Load Shipment (Truck should be 'present' now) ---
    logger.info(f"--- Test Step: load_shipment (Shipment ID: {shipment_id}, Truck ID: {mock_truck_id}) ---")
    success, resp = service.load_shipment(
        warehouse_id=warehouse_id,
        truck_id=mock_truck_id,
        shipment_id=shipment_id
    )
    logger.info(f"load_shipment -> success={success}, response={resp}")
    # Check for specific error if truck wasn't simulated correctly
    if not success and "truck not here" in str(resp).lower():
         logger.error(f"Load failed because truck {mock_truck_id} was not simulated at warehouse {warehouse_id} correctly.")
    assert success, f"load_shipment command failed. Response: {resp}."

    # --- 5.5 Check ALoaded and Status Update ---
    # Wait for ALoaded notification and check status
    # The background thread should update status to 'loaded' upon receiving ALoaded.
    success, status = wait_for_shipment_status(shipment_id, 'loaded', service, timeout=30)
    assert success, f"Shipment {shipment_id} did not reach 'loaded' status. Final status: {status}"

    # --- 5.6 Simulate UPS Delivery ---
    # In a real system, ALoaded would trigger Amazon to notify UPS.
    # UPS would send UGoDeliver(truckid=X, packages=[{packageid=shipment_id, x=DestX, y=DestY}]) to World Sim.
    # World Sim would send UDeliveryMade(truckid=X, packageid=shipment_id) when delivered.
    # World Sim would send UFinished(status='idle') when all deliveries for that truck are done.
    # UPS would notify Amazon via webhook (/api/ups/package-delivered).
    # Amazon updates DB status to 'delivered'.

    # ** MOCK / SIMULATION for this test **
    logger.info("--- Test Step: Simulating UPS Delivery ---")
    logger.info(f"Simulating truck {mock_truck_id} delivering shipment {shipment_id}.")
    # Manually trigger the status update that the webhook would cause:
    try:
        with app.app_context():
             shipment = db.session.get(Shipment, shipment_id)
             if shipment and shipment.status == 'loaded':
                  # Simulate passage of time for 'delivering' state
                  shipment.status = 'delivering'
                  db.session.commit()
                  logger.info(f"Shipment {shipment_id} status set to 'delivering'. Waiting...")
                  time.sleep(10) # Simulate delivery time

                  # Simulate final delivery
                  shipment.status = 'delivered'
                  db.session.commit()
                  logger.info(f"Shipment {shipment_id} status set to 'delivered'.")
             elif not shipment:
                  logger.error(f"Shipment {shipment_id} not found for delivery simulation.")
                  assert False, "Shipment not found during mock delivery."
             else:
                   logger.warning(f"Shipment {shipment_id} status was '{shipment.status}', expected 'loaded' for delivery simulation.")
                   assert False, "Incorrect status for mock delivery." # Fail if not loaded before delivery
    except Exception as e:
         logger.error(f"Error during mock delivery simulation: {e}", exc_info=True)
         assert False, "Mock delivery simulation failed."


    # --- 5.7 Test: Query Package Status (Post-Delivery) ---
    logger.info(f"--- Test Step: query_package (Shipment ID: {shipment_id}) ---")
    # Query status after simulated delivery
    success, status = service.query_package(package_id=shipment_id)
    logger.info(f"query_package -> success={success}, status={status}")
    assert success, f"query_package command failed. Status/Error: {status}."
    assert status == 'delivered', f"Expected status 'delivered' but got '{status}'."
    logger.info("--- Test: Full Flow Completed Successfully ---")


def test_boundary_cases(service, world_id):
    """Tests various boundary and error conditions."""
    logger.info("--- Starting Test: Boundary Cases ---")
    warehouse_id = 1

    # --- Test: Duplicate Product ID with Different Description ---
    # The spec says behavior is undefined. Test how *this* simulator handles it.
    # It might accept it, overwrite, or return an error. We'll check for non-failure.
    logger.info("--- Test Step: Duplicate Product ID Buy ---")
    prod_id = int(time.time()) # Use a unique ID for this test
    desc1 = "First Description"
    desc2 = "Second Description"
    logger.info(f"Buying Product ID {prod_id} with description '{desc1}'")
    success1, resp1 = service.buy_product(warehouse_id, prod_id, desc1, 1)
    assert success1, f"First buy failed: {resp1}"
    time.sleep(2) # Small delay
    logger.info(f"Buying Product ID {prod_id} again with description '{desc2}'")
    success2, resp2 = service.buy_product(warehouse_id, prod_id, desc2, 1)
    # We expect this *not* to fail catastrophically, even if behavior is undefined.
    # A specific assertion depends on expected behavior (e.g., assert success2 is True/False, or check resp2)
    logger.info(f"Second buy -> success={success2}, response={resp2}. (Note: Behavior for different descriptions is undefined)")
    assert success2, f"Second buy with different description failed: {resp2}" # Assume it should ACK

    # --- Test: Duplicate Package ID ---
    # World requires unique package IDs
    logger.info("--- Test Step: Duplicate Package ID Pack ---")
    dup_shipment_id = int(time.time()) + 100 # Unique ID for this test
    items_to_pack = [{"product_id": 101, "description": "TestItem", "quantity": 1}]
    logger.info(f"Packing shipment {dup_shipment_id} (first time)")
    success1, resp1 = service.pack_shipment(warehouse_id, dup_shipment_id, items_to_pack)
    assert success1, f"First pack failed: {resp1}"
    time.sleep(5) # Wait for potential processing
    logger.info(f"Packing shipment {dup_shipment_id} (second time - expecting failure)")
    success2, resp2 = service.pack_shipment(warehouse_id, dup_shipment_id, items_to_pack)
    # Expecting the second call to fail
    assert not success2, f"Second pack with duplicate shipment ID {dup_shipment_id} unexpectedly succeeded."
    logger.info(f"Second pack -> success={success2}, response={resp2}. (Failure expected)")
    if not isinstance(resp2, str) or "error" not in resp2.lower():
         logger.warning(f"Duplicate package ID did not return an explicit error message in response: {resp2}")

    # --- Test: Load Shipment When Truck Not Present ---
    logger.info("--- Test Step: Load Shipment with No Truck ---")
    no_truck_shipment_id = int(time.time()) + 200
    # 1. Buy and Pack the item first
    logger.info(f"Setting up: Buying product 101 for shipment {no_truck_shipment_id}")
    buy_success, _ = service.buy_product(warehouse_id, 101, "NoTruckTest", 1)
    assert buy_success, "Setup failed: Could not buy product."
    time.sleep(10) # Wait for arrival
    logger.info(f"Setting up: Packing shipment {no_truck_shipment_id}")
    pack_success, _ = service.pack_shipment(warehouse_id, no_truck_shipment_id, [{"product_id": 101, "description": "NoTruckTest", "quantity": 1}])
    assert pack_success, "Setup failed: Could not pack shipment."
    success, status = wait_for_shipment_status(no_truck_shipment_id, 'packed', service, timeout=30)
    assert success, f"Setup failed: Shipment {no_truck_shipment_id} did not reach 'packed' status."

    # 2. Attempt to load WITHOUT simulating truck arrival
    mock_truck_id_absent = 99
    logger.info(f"Attempting to load shipment {no_truck_shipment_id} onto truck {mock_truck_id_absent} (which is not there)")
    load_success, load_resp = service.load_shipment(warehouse_id, mock_truck_id_absent, no_truck_shipment_id)
    assert not load_success, f"Load command with absent truck {mock_truck_id_absent} unexpectedly succeeded."
    logger.info(f"Load attempt -> success={load_success}, response={load_resp}. (Failure expected)")
    # Assert specific error message if possible
    assert isinstance(load_resp, str) and ("truck" in load_resp.lower() and ("not" in load_resp.lower() or "unavailable" in load_resp.lower() or "must be at the warehouse" in load_resp.lower())), f"Expected truck error message, but got: {load_resp}"
    logger.info("Correctly failed to load onto non-present truck.")

    # --- Test: UPS Changing Delivery Address (Conceptual) ---
    # This requires simulating the UPS side interaction (UGoDeliver commands).
    # logger.info("--- Test Step: Change Delivery Address (Conceptual) ---")
    # logger.info("Conceptual Steps:")
    # logger.info("1. Complete steps up to ALoaded for a new shipment (e.g., shipment_id_addr_change).")
    # logger.info("2. Simulate UPS sending UGoDeliver for shipment_id_addr_change to Address A (e.g., (50,50)).")
    # logger.info("3. BEFORE delivery confirmation, simulate UPS sending *another* UGoDeliver for the *same* shipment_id_addr_change to Address B (e.g., (70,70)).")
    # logger.info("4. Simulate delivery completion.")
    # logger.info("5. Verify through logs or DB state that the final delivery occurred at Address B.")
    # logger.info("(Skipping actual implementation as it requires UPS-side simulation)")

    logger.info("--- Test: Boundary Cases Completed ---")

# --------------------------
# 6. Main Execution Logic
# --------------------------
def main():
    # Prepare the test environment database record
    logger.info("Setting up test environment...")
    setup_test_env()
    logger.info("Test environment setup complete.")

    # Connect to simulator
    service, world_id = initialize_and_connect()
    if not service:
        logger.error("Failed to initialize or connect to World Simulator. Aborting tests.")
        return

    # Run Tests
    try:
        test_full_flow(service, world_id)
        test_boundary_cases(service, world_id)

        # Add more test functions here if needed

    except AssertionError as e:
         logger.error(f"!!!!!!!! Test Assertion Failed: {e} !!!!!!!!!!")
    except Exception as e:
        logger.error(f"!!!!!!!! An unexpected error occurred during tests: {e} !!!!!!!!!!", exc_info=True)
    finally:
        # --- Disconnect ---
        logger.info("Disconnecting from World Simulator...")
        # Call disconnect within app context in case it needs context for cleanup
        # (WorldSimulatorService handles context internally if app was passed)
        service.disconnect() # Sends disconnect command
        logger.info("Disconnected. Test finished.")

# --- Script Entry Point ---
if __name__ == '__main__':
    try:
        # Execute the main test function
        main()
    finally:
        # Ensure the application context is popped, regardless of success or failure
        if 'tx' in locals() and tx: # Check if tx was successfully assigned
           try:
               tx.pop() # Pop the global application context
               logger.info("Flask application context popped.")
           except RuntimeError as e:
               # Handle cases where context might have been popped elsewhere or never pushed properly
               logger.warning(f"Could not pop application context: {e}")
           except Exception as e:
               # Handle other unexpected errors during context popping
                logger.error(f"Unexpected error popping context: {e}", exc_info=True)
        logger.info("Script finished.")