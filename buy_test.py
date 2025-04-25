import sys
import os
import time
import logging
import threading
import random
from flask import Flask

# Ensure the app modules can be imported
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, '.'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
    sys.path.insert(0, os.path.join(project_root, 'app')) # Add app directory too

# Import necessary components AFTER setting the path
try:
    from app.model import db, Warehouse, Product, ProductCategory, User # Import Product
    from app.services.world_simulator_service import WorldSimulatorService
except ImportError as e:
    print(f"Error importing application modules: {e}")
    print(f"Please ensure this script is in the 'amazon-ups' directory and run as python <script_name>.py")
    sys.exit(1)

# --- Configuration ---
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:abc123@db:5432/mini_amazon')
WORLD_HOST = os.environ.get('WORLD_HOST', 'server')
WORLD_PORT = int(os.environ.get('WORLD_PORT', '23456'))
CONNECT_WORLD_ID = None # Create a new world
BUY_WAREHOUSE_ID = 1 # Warehouse ID to buy for / initialize
BUY_QUANTITY_PER_PRODUCT = 2 # Quantity to buy for EACH product
MAX_PRODUCTS_TO_BUY = 10 # Limit how many products to buy to avoid flooding (adjust as needed)
DELAY_BETWEEN_BUYS = 0.5 # Seconds delay between each buy request
WAIT_TIME_AFTER_ALL_BUYS = 20 # Seconds to wait after sending all buy commands

# --- Flask App Setup (for context) ---
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev')
db.init_app(app)

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger("MultiBuyTest") # Changed logger name

# --- Helper: Ensure Warehouse --- (Product check is now part of the main logic)
def ensure_warehouse_exists():
    """Ensures the target warehouse exists."""
    with app.app_context():
        try:
            warehouse = db.session.get(Warehouse, BUY_WAREHOUSE_ID)
            if not warehouse:
                logger.warning(f"Warehouse {BUY_WAREHOUSE_ID} not found. Creating...")
                warehouse = Warehouse(warehouse_id=BUY_WAREHOUSE_ID, x=random.randint(5,95), y=random.randint(5,95), active=True)
                db.session.add(warehouse)
                db.session.commit()
                logger.info(f"Created Warehouse {BUY_WAREHOUSE_ID}")
            else:
                logger.info(f"Warehouse {BUY_WAREHOUSE_ID} found.")
            return True
        except Exception as e:
            logger.error(f"Error ensuring warehouse exists: {e}", exc_info=True)
            db.session.rollback()
            return False

# --- Main Execution ---
def main():
    logger.info("--- Starting Multi-Product Buy Test Script ---")

    with app.app_context():
        logger.info("Flask application context pushed for main execution.")

        # 1. Ensure necessary Warehouse exists
        logger.info(f"Ensuring test Warehouse {BUY_WAREHOUSE_ID} exists in DB...")
        if not ensure_warehouse_exists():
            logger.error("Failed to ensure test warehouse exists. Aborting.")
            return
        logger.info("Warehouse check complete.")

        # 2. Initialize World Simulator Service
        logger.info(f"Initializing World Simulator Service (Target: {WORLD_HOST}:{WORLD_PORT})...")
        world_service = WorldSimulatorService(app=app, host=WORLD_HOST, port=WORLD_PORT)

        # 3. Prepare for Connection
        logger.info(f"Attempting to connect to World ID: {'New World' if CONNECT_WORLD_ID is None else CONNECT_WORLD_ID}...")
        init_wh = []
        if CONNECT_WORLD_ID is None:
            warehouse_to_init = db.session.get(Warehouse, BUY_WAREHOUSE_ID)
            if warehouse_to_init:
                init_wh = [warehouse_to_init]
                logger.info(f"Will initialize new world with Warehouse ID: {BUY_WAREHOUSE_ID}")
            else:
                logger.error(f"Cannot find Warehouse {BUY_WAREHOUSE_ID} to initialize new world. Aborting.")
                return

        # 4. Connect to World
        world_id, result = world_service.connect(world_id=CONNECT_WORLD_ID, init_warehouses=init_wh)

        if not world_service.connected:
            logger.error(f"Failed to connect to World Simulator: {result}. Exiting.")
            return

        effective_world_id = world_service.world_id
        logger.info(f"Successfully connected to World ID: {effective_world_id}. Result: {result}")

        # 5. Fetch Products from DB
        logger.info(f"Fetching up to {MAX_PRODUCTS_TO_BUY} products from database...")
        try:
            products_to_buy = db.session.query(Product).limit(MAX_PRODUCTS_TO_BUY).all()
            if not products_to_buy:
                logger.warning("No products found in the database to buy.")
            else:
                logger.info(f"Found {len(products_to_buy)} products. Starting buy requests...")

                # 6. Send Buy Requests for Each Product
                buy_commands_sent = 0
                for product in products_to_buy:
                    logger.info(f"  Sending BUY: WH={BUY_WAREHOUSE_ID}, ProdID={product.product_id}, Name='{product.product_name}', Qty={BUY_QUANTITY_PER_PRODUCT}")
                    try:
                        success, buy_response = world_service.buy_product(
                            warehouse_id=BUY_WAREHOUSE_ID,
                            product_id=product.product_id,
                            # Use the actual product name as description
                            description=product.product_name,
                            quantity=BUY_QUANTITY_PER_PRODUCT
                        )
                        if success:
                            # logger.debug(f"  BUY command for {product.product_id} sent successfully. Msg: {buy_response}")
                            buy_commands_sent += 1
                        else:
                            logger.error(f"  Failed to send BUY command for {product.product_id}. Response: {buy_response}")
                        # Add delay between requests
                        time.sleep(DELAY_BETWEEN_BUYS)

                    except Exception as e:
                        logger.error(f"  An error occurred during buy_product for {product.product_id}: {e}", exc_info=True)
                        time.sleep(DELAY_BETWEEN_BUYS) # Still wait before next attempt

                logger.info(f"Finished sending buy requests. Total commands sent: {buy_commands_sent}/{len(products_to_buy)}")

        except Exception as e:
            logger.error(f"Error fetching products from DB: {e}", exc_info=True)


        # 7. Wait and Disconnect
        logger.info(f"Waiting {WAIT_TIME_AFTER_ALL_BUYS} seconds before disconnecting...")
        time.sleep(WAIT_TIME_AFTER_ALL_BUYS)

        logger.info("Disconnecting from World Simulator...")
        world_service.disconnect()
        logger.info("Disconnected.")

    # Context automatically popped
    logger.info("Flask application context popped.")
    logger.info("--- Multi-Product Buy Test Script Finished ---")

if __name__ == "__main__":
    main()
##docker compose exec web python buy_test.py
