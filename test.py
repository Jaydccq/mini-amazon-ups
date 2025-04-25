import sys
import os
import time
import logging
import threading # Needed for Event
from flask import Flask
# Import necessary models including User and ProductCategory
# Ensure these models exist in your app.model module
from app.model import db, Warehouse, Product, ProductCategory, User, Shipment, OrderProduct
# Import WorldSimulatorService
from app.services.world_simulator_service import WorldSimulatorService

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
# This default matches the second docker-compose.yml's internal perspective
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL',
    'postgresql://postgres:abc123@db:5432/mini_amazon' # Default changed to 'db' hostname
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

# --------------------------
# 2. Setup test DB record
# --------------------------
def setup_test_env():
    """
    Ensure a warehouse (ID=1) and product (ID=101) exist in the database for testing.
    Requires application context for database operations.
    """
    with app.app_context(): # Use context manager for safety
        try:
            logger.info("Checking for test Warehouse (ID=1)...")
            # Use db.session.get to fetch by primary key (preferred)
            w = db.session.get(Warehouse, 1)
            if not w:
                # If warehouse doesn't exist, create it
                w = Warehouse(warehouse_id=1, x=10, y=10, active=True)
                db.session.add(w)
                # Commit here to ensure warehouse exists before product check
                db.session.commit()
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
                      # Assuming admin user from init.sql or __init__.py exists
                      seller = db.session.query(User).filter_by(email='admin@example.com').first()
                      if not seller: # If admin still not found, create a basic one (adjust as needed)
                           seller = User(email='test_seller@example.com', first_name='Test', last_name='Seller', is_seller=True)
                           seller.set_password('password')
                           db.session.add(seller)
                           # Commit seller before category check
                           db.session.commit()
                           logger.info("Created basic test seller.")

                 # Find a category or create one
                 category = db.session.query(ProductCategory).first()
                 if not category:
                      category = ProductCategory(category_name='Test Category')
                      db.session.add(category)
                      # Commit category before creating product
                      db.session.commit()
                      logger.info("Created basic test category.")

                 logger.info("Creating test Product ID=101 (TestItem)...")
                 test_prod = Product(product_id=101, product_name="TestItem", description="Item for testing", price=9.99, owner_id=seller.user_id, category_id=category.category_id)
                 db.session.add(test_prod)
                 # Commit the product
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
# --------------------------------------
def initialize_and_connect():
    """Initializes warehouses, connects to the simulator, and returns the service instance."""
    initial_warehouses = []
    # Use app context for DB operations
    with app.app_context():
        try:
            # Fetch the specific warehouse used in tests (needs app context)
            test_warehouse = db.session.get(Warehouse, 1)
            if test_warehouse:
                # *** No need to pass warehouses when connecting to existing world ***
                # initial_warehouses.append(test_warehouse)
                logger.info(f"Verified Warehouse ID=1 exists (Coords: {test_warehouse.x},{test_warehouse.y}).")
            else:
                 # If warehouse not found after setup, cannot proceed
                 logger.error("Test warehouse ID=1 not found in database after setup! Cannot connect to world.")
                 return None # Cannot proceed without the warehouse
        except Exception as e:
            logger.error(f"Error fetching warehouse for verification: {e}", exc_info=True)
            db.session.rollback() # Rollback if DB access failed
            return None

    # Get World Simulator host and port from environment variables or use defaults
    # These defaults match the second docker-compose.yml's configuration
    host = os.environ.get('WORLD_HOST', 'server') # Default changed to match docker-compose
    port = int(os.environ.get('WORLD_PORT', '23456')) # Amazon connection port [cite: 4]
    logger.info(f"Attempting connection to World Simulator at {host}:{port}...")

    # Create WorldSimulatorService instance, passing the Flask app object
    # Passing 'app' allows the service's background thread to create app contexts for DB operations
    service = WorldSimulatorService(app=app, host=host, port=port)

    # --- Connect to World Simulator ---
    # Attempt to connect to an existing world ID=1
    existing_world_id = 1
    logger.info(f"Attempting to connect to existing world ID: {existing_world_id}")
    # Pass init_warehouses=None because we connect to an existing world
    world_id, result = service.connect(world_id=existing_world_id, init_warehouses=None)

    if world_id is None or not result == "connected!":
        # Check if connection failed
        logger.error(f"Connection failed: {result}")
        return None # Cannot continue
    logger.info(f"Successfully connected! (World ID: {world_id}), Result: {result}") # [cite: 15]

    # --- Set Simulation Speed (Optional, for testing) ---
    try:
        # Increase simulation speed for potentially faster test feedback
        sim_speed_to_set = 1000 # Example speed
        sim_speed_set_locally = service.set_sim_speed(sim_speed_to_set) # [cite: 19]

        if sim_speed_set_locally:
            logger.info(f"Simulation speed set command sent ({sim_speed_to_set}).")
        else:
            logger.warning("Failed to queue simulation speed command (service disconnected or queue error?).")
    except Exception as e:
        # Catch potential exceptions
        logger.warning(f"set_sim_speed failed locally or not supported; proceeding without speed change. Error: {e}")

    return service, world_id

# --------------------------
# 4. Test Helper Functions
# --------------------------
def wait_for_shipment_status(shipment_id, target_status, service, timeout=30):
    """Polls the database for the shipment status until it reaches the target or timeout."""
    logger.info(f"Waiting for shipment {shipment_id} to reach status '{target_status}' (timeout: {timeout}s)...")
    start_time = time.time()
    last_status = 'Unknown'
    with app.app_context(): # Use context for the whole loop
        while time.time() - start_time < timeout:
            try:
                shipment = db.session.get(Shipment, shipment_id)
                if shipment:
                    last_status = shipment.status
                    if shipment.status == target_status:
                        logger.info(f"Shipment {shipment_id} reached status '{target_status}' in DB.")
                        return True, shipment.status
                else:
                    last_status = 'Not Found in DB'

                # Optionally, query the simulator directly as a fallback
                # Note: This requires query_package to be implemented and working
                # query_success, current_status = service.query_package(package_id=shipment_id)
                # if query_success and current_status == target_status:
                #     logger.info(f"Shipment {shipment_id} reached status '{target_status}' (verified via query).")
                #     return True, current_status
                # elif query_success:
                #     last_status = f"DB: {last_status}, Query: {current_status}"

                time.sleep(2) # Check every 2 seconds
            except Exception as e:
                 logger.error(f"Error polling shipment status: {e}", exc_info=True)
                 time.sleep(2) # Wait before retrying DB query


    logger.warning(f"Timeout waiting for shipment {shipment_id} to reach status '{target_status}'. Last seen status: {last_status}")
    return False, last_status

# --------------------------
# 5. Test Scenarios
# --------------------------

def test_full_flow(service, world_id):
    """Tests the basic BUY -> PACK -> LOAD flow as per project spec Figure 1[cite: 94]."""
    logger.info("--- Starting Test: Full Flow ---")
    if not service or not service.connected:
        logger.error("Service not connected. Aborting test_full_flow.")
        return # Cannot proceed

    warehouse_id = 1 # Using the one set up in setup_test_env
    product_info = {"product_id": 101, "description": "TestItem", "quantity": 5} # Using product from setup
    # Create a unique shipment ID for this test run, potentially based on time
    shipment_id = int(time.time() * 1000) # Use milliseconds for higher uniqueness chance
    logger.info(f"Using Shipment ID: {shipment_id}")


    # --- 5.1 Test: Buy Product [cite: 33] ---
    logger.info(f"--- Test Step: buy_product (Product ID: {product_info['product_id']}, WH: {warehouse_id}) ---")
    success, resp = service.buy_product(
        warehouse_id=warehouse_id,
        product_id=product_info["product_id"],
        description=product_info["description"],
        quantity=product_info["quantity"]
    )
    logger.info(f"buy_product -> success={success}, response='{resp}'")
    assert success, f"buy_product command failed. Response: {resp}."
    # Wait for AArrived notification [cite: 41] (implicitly handled by background thread)
    # Adding a delay. In a real test, might check DB inventory or listen for an event.
    logger.info("Waiting for product arrival notification (approx 5-10s)...")
    time.sleep(10) # Adjust based on sim speed or add explicit check

    # --- 5.2 Test: Pack Shipment [cite: 37] ---
    # Use only 1 item from the bought quantity for this shipment
    items_to_pack = [{"product_id": product_info["product_id"], "description": product_info["description"], "quantity": 1}]
    logger.info(f"--- Test Step: pack_shipment (Shipment ID: {shipment_id}, WH: {warehouse_id}) ---")
    success, resp = service.pack_shipment(
        warehouse_id=warehouse_id,
        shipment_id=shipment_id,
        items=items_to_pack
    )
    logger.info(f"pack_shipment -> success={success}, response='{resp}'")
    assert success, f"pack_shipment command failed. Response: {resp}."
    # Wait for AReady notification [cite: 43] and check status in DB
    success, status = wait_for_shipment_status(shipment_id, 'packed', service, timeout=45) # Increased timeout
    assert success, f"Shipment {shipment_id} did not reach 'packed' status. Final status: {status}"

    # --- 5.3 Simulate UPS Pickup Request and Arrival ---
    # This part simulates the interaction described in Figure 1 [cite: 94] where UPS sends a truck.
    logger.info("--- Test Step: Simulating UPS Pickup & Truck Arrival ---")
    # In a real system: Amazon gets AReady -> Notifies UPS -> UPS sends UGoPickup -> World Sim sends UFinished(arrive warehouse) -> UPS notifies Amazon via webhook.
    # We MOCK the final step: UPS notifying Amazon that the truck has arrived.
    mock_truck_id = 5 # Example truck ID
    logger.info(f"Simulating truck {mock_truck_id} arrival at warehouse {warehouse_id} for shipment {shipment_id}.")
    # Manually update the shipment in the DB as the webhook would
    try:
        with app.app_context(): # Ensure context for DB operations
             shipment = db.session.get(Shipment, shipment_id)
             if shipment and shipment.status == 'packed':
                  shipment.truck_id = mock_truck_id
                  # IMPORTANT: Do NOT set status to 'loading' here.
                  # The 'load_shipment' command itself should trigger the 'loading' phase in the sim,
                  # and the subsequent 'ALoaded' response [cite: 44] should trigger the status update to 'loaded'.
                  db.session.commit()
                  logger.info(f"Updated Shipment {shipment_id} in DB with truck_id {mock_truck_id}.")
             elif not shipment:
                  logger.error(f"Shipment {shipment_id} not found in DB for truck arrival simulation.")
                  assert False, "Shipment not found during mock truck arrival."
             else:
                  # If status is not 'packed', loading will likely fail. Assert failure.
                  logger.error(f"Shipment {shipment_id} status was '{shipment.status}', expected 'packed' for truck arrival. Load will fail.")
                  assert False, f"Incorrect status '{shipment.status}' before loading."
    except Exception as e:
         logger.error(f"Error during mock truck arrival simulation: {e}", exc_info=True)
         db.session.rollback()
         assert False, "Mock truck arrival simulation failed."

    # --- 5.4 Test: Load Shipment [cite: 39] ---
    # Truck is now simulated to be present at the warehouse.
    logger.info(f"--- Test Step: load_shipment (Shipment ID: {shipment_id}, Truck ID: {mock_truck_id}, WH: {warehouse_id}) ---")
    success, resp = service.load_shipment(
        warehouse_id=warehouse_id,
        truck_id=mock_truck_id,
        shipment_id=shipment_id
    )
    logger.info(f"load_shipment -> success={success}, response='{resp}'")
    assert success, f"load_shipment command failed. Response: {resp}." # Sim should ACK the command

    # --- 5.5 Check ALoaded Notification and Status Update ---
    # Wait for ALoaded notification [cite: 44] and check DB status update to 'loaded'
    success, status = wait_for_shipment_status(shipment_id, 'loaded', service, timeout=45) # Increased timeout
    assert success, f"Shipment {shipment_id} did not reach 'loaded' status. Final status: {status}"

    # --- End of Amazon-Controlled Flow ---
    # Delivery steps (UGoDeliver[cite: 50], UDeliveryMade [cite: 60]) are controlled by UPS.
    # Amazon might receive a final /api/ups/package-delivered webhook.
    logger.info("--- Test: Amazon-controlled flow (Buy, Pack, Load) Completed Successfully ---")
    # Optional: Simulate final delivery update for completeness
    # try:
    #     with app.app_context():
    #         shipment = db.session.get(Shipment, shipment_id)
    #         if shipment and shipment.status == 'loaded':
    #             shipment.status = 'delivered' # Simulate final webhook update
    #             # Update order status if this was the only shipment
    #             order = db.session.get(Order, shipment.order_id)
    #             if order:
    #                  all_shipments_delivered = all(s.status == 'delivered' for s in order.shipments)
    #                  if all_shipments_delivered:
    #                       order.order_status = 'Fulfilled'
    #             db.session.commit()
    #             logger.info(f"Simulated final delivery for shipment {shipment_id}.")
    # except Exception as e:
    #     logger.error(f"Error during final delivery simulation: {e}")
    #     db.session.rollback()


def test_boundary_cases(service, world_id):
    """Tests various boundary and error conditions."""
    logger.info("--- Starting Test: Boundary Cases ---")
    if not service or not service.connected:
        logger.error("Service not connected. Aborting test_boundary_cases.")
        return # Cannot proceed

    warehouse_id = 1

    # --- Test: Buy Duplicate Product ID with Different Description ---
    # Project spec[cite: 36]: "if you use different descriptions for the same product id, the behavior is undefined"
    # Test aims to ensure it doesn't crash the system and likely gets acknowledged.
    logger.info("--- Test Step: Duplicate Product ID Buy (Different Description) ---")
    boundary_prod_id = int(time.time() * 1000) + 1 # Unique ID
    desc1 = "First Desc"
    desc2 = "Second Desc"
    logger.info(f"Buying Product ID {boundary_prod_id} with description '{desc1}'")
    success1, resp1 = service.buy_product(warehouse_id, boundary_prod_id, desc1, 1)
    assert success1, f"First buy failed: {resp1}"
    time.sleep(2) # Small delay
    logger.info(f"Buying Product ID {boundary_prod_id} again with description '{desc2}'")
    success2, resp2 = service.buy_product(warehouse_id, boundary_prod_id, desc2, 1)
    logger.info(f"Second buy -> success={success2}, response='{resp2}'. (Note: Behavior is undefined, checking for non-failure)")
    assert success2, f"Second buy with different description failed: {resp2}" # Assuming it should ACK the command

    # --- Test: Pack Duplicate Shipment ID ---
    # Package IDs must be unique for the world[cite: 99, 100]. Expecting the second pack to fail.
    logger.info("--- Test Step: Duplicate Shipment ID Pack ---")
    dup_shipment_id = int(time.time() * 1000) + 2 # Unique ID for this test
    items_to_pack = [{"product_id": 101, "description": "TestItem", "quantity": 1}]
    logger.info(f"Packing shipment {dup_shipment_id} (first time)")
    success1, resp1 = service.pack_shipment(warehouse_id, dup_shipment_id, items_to_pack)
    assert success1, f"First pack failed: {resp1}"
    # Wait for the first pack to be processed potentially
    success_wait, status_wait = wait_for_shipment_status(dup_shipment_id, 'packed', service, timeout=30)
    assert success_wait, f"First pack for {dup_shipment_id} did not reach 'packed' status."

    logger.info(f"Packing shipment {dup_shipment_id} (second time - expecting failure)")
    success2, resp2 = service.pack_shipment(warehouse_id, dup_shipment_id, items_to_pack)
    # Expecting the second call to fail or return an error message [cite: 45]
    logger.info(f"Second pack -> success={success2}, response='{resp2}'. (Failure expected)")
    assert not success2 or "error" in str(resp2).lower(), f"Second pack with duplicate shipment ID {dup_shipment_id} did not fail as expected. Response: {resp2}"

    # --- Test: Load Shipment When Truck Not Present ---
    # Project spec[cite: 39]: "the truck MUST be at the warehouse" for loading to succeed.
    logger.info("--- Test Step: Load Shipment with No Truck ---")
    no_truck_shipment_id = int(time.time() * 1000) + 3
    # 1. Buy and Pack the item first
    logger.info(f"Setting up: Buying product 101 for shipment {no_truck_shipment_id}")
    buy_success, _ = service.buy_product(warehouse_id, 101, "NoTruckTest", 1)
    assert buy_success, "Setup failed: Could not buy product."
    time.sleep(10) # Wait for arrival
    logger.info(f"Setting up: Packing shipment {no_truck_shipment_id}")
    pack_success, _ = service.pack_shipment(warehouse_id, no_truck_shipment_id, [{"product_id": 101, "description": "NoTruckTest", "quantity": 1}])
    assert pack_success, "Setup failed: Could not pack shipment."
    success_wait_pack, status_wait_pack = wait_for_shipment_status(no_truck_shipment_id, 'packed', service, timeout=30)
    assert success_wait_pack, f"Setup failed: Shipment {no_truck_shipment_id} did not reach 'packed' status."

    # 2. Attempt to load WITHOUT simulating truck arrival
    mock_truck_id_absent = 99 # A truck ID assumed not to be at the warehouse
    logger.info(f"Attempting to load shipment {no_truck_shipment_id} onto truck {mock_truck_id_absent} (expected absent)")
    load_success, load_resp = service.load_shipment(warehouse_id, mock_truck_id_absent, no_truck_shipment_id)
    logger.info(f"Load attempt -> success={load_success}, response='{load_resp}'. (Failure or error expected)")
    # Expecting failure or an error message in the response [cite: 45]
    assert not load_success or "error" in str(load_resp).lower(), f"Load command with absent truck {mock_truck_id_absent} did not fail as expected. Response: {load_resp}"
    if not load_success:
        logger.info("Correctly failed to load onto non-present truck.")
    elif "error" in str(load_resp).lower():
        logger.info(f"Load command acknowledged but returned error as expected: {load_resp}")


    logger.info("--- Test: Boundary Cases Completed ---")

# --------------------------
# 6. Main Execution Logic
# --------------------------
def main():
    global tx # Make tx global so it can be accessed in finally block
    tx = None
    try:
        # Push context manually for setup
        tx = app.app_context()
        tx.push()
        logger.info("Flask application context pushed for setup.")

        # Prepare the test environment database records
        logger.info("Setting up test environment...")
        setup_test_env()
        logger.info("Test environment setup complete.")

        # Connect to simulator
        service, world_id = initialize_and_connect()
        if not service:
            logger.error("Failed to initialize or connect to World Simulator. Aborting tests.")
            return

        # Run Tests
        # Ensure tests run within the app context if they need direct DB access
        # Note: service methods handle their own context if 'app' was passed during init
        test_full_flow(service, world_id)
        test_boundary_cases(service, world_id)

        # Add more test functions here if needed

    except AssertionError as e:
         logger.error(f"!!!!!!!! Test Assertion Failed: {e} !!!!!!!!!!", exc_info=True) # Add exc_info
    except Exception as e:
        logger.error(f"!!!!!!!! An unexpected error occurred during tests: {e} !!!!!!!!!!", exc_info=True)
    finally:
        # Disconnect if service was initialized
        if 'service' in locals() and service and service.connected:
            logger.info("Disconnecting from World Simulator...")
            service.disconnect() # Sends disconnect command
            logger.info("Disconnected.")

        # Ensure the application context is popped
        if tx: # Check if tx was successfully assigned and pushed
           try:
               tx.pop() # Pop the global application context
               logger.info("Flask application context popped.")
           except RuntimeError as e:
               # Handle cases where context might have been popped elsewhere or already invalid
               logger.warning(f"Could not pop application context: {e}")
           except Exception as e:
               # Handle other unexpected errors during context popping
                logger.error(f"Unexpected error popping context: {e}", exc_info=True)
        logger.info("Test script finished.")


# --- Script Entry Point ---
if __name__ == '__main__':
    main()