import os
import random
import sys
from datetime import datetime
from faker import Faker
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError, OperationalError

# --- Configuration ---
# Get database connection string from environment variable or use default
# Option 1a: Simplest form (relies on defaults)
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql:///mini_amazon')

NUM_USERS = 50
NUM_SELLERS = 5
NUM_CATEGORIES = 5
NUM_PRODUCTS_PER_CATEGORY = 20
NUM_WAREHOUSES = 10
MAX_INITIAL_INVENTORY = 100
NUM_ORDERS_PER_USER = 5
MAX_ITEMS_PER_ORDER = 5
NUM_SHIPMENTS_TO_CREATE = int(NUM_USERS * NUM_ORDERS_PER_USER * 0.9) # Assume 90% of orders get a shipment

# --- Dynamically Import Application Models ---
# Assume this script runs from the project root
project_root = os.path.dirname(os.path.abspath(__file__))
app_dir = os.path.join(project_root, 'app')
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)
    sys.path.insert(0, project_root) # Ensure 'app' can be found

try:
    # Try importing from app.model
    from app.model import db as imported_db, User, ProductCategory, Product, Warehouse, WarehouseProduct, Cart, CartProduct, Order, OrderProduct, Shipment, ShipmentItem
    # If importing 'db' directly conflicts with local variables, rename it
    db_models = {
        'User': User, 'ProductCategory': ProductCategory, 'Product': Product,
        'Warehouse': Warehouse, 'WarehouseProduct': WarehouseProduct, 'Cart': Cart,
        'CartProduct': CartProduct, 'Order': Order, 'OrderProduct': OrderProduct,
        'Shipment': Shipment, 'ShipmentItem': ShipmentItem
    }
except ImportError as e:
    print(f"Error: Could not import application models. Ensure the script's location relative to the project structure is correct and dependencies are installed.")
    print(f"Import Error: {e}")
    print(f"Current Python Path: {sys.path}")
    sys.exit(1) # Cannot continue, exit

# Initialize Faker
fake = Faker()

# --- Database Connection ---
try:
    engine = create_engine(DATABASE_URL)
    # Test connection
    connection = engine.connect()
    connection.close()
    print(f"Successfully connected to database: {DATABASE_URL.split('@')[-1]}") # Hide password
except OperationalError as e:
     print(f"Error: Could not connect to database {DATABASE_URL.split('@')[-1]}. Ensure the database is running and the connection string is correct.")
     print(f"SQLAlchemy Error: {e}")
     sys.exit(1)
except Exception as e:
    print(f"An unknown error occurred while connecting to the database: {e}")
    sys.exit(1)

Session = sessionmaker(bind=engine)
session = Session()

# --- Data Generation Functions (using imported models) ---

def create_users(n_users, n_sellers):
    """Creates regular users and seller users."""
    User = db_models['User']
    users = []
    # Ensure admin user exists (check from create_database.sql)
    admin = session.query(User).filter_by(email='admin@example.com').first()
    if not admin:
        print("Creating default admin user...")
        admin = User(email='admin@example.com', first_name='Admin', last_name='User', is_seller=True)
        admin.set_password('admin') # Use the method from the model to hash the password
        session.add(admin)
        # Note: Don't commit here yet, add all users together
        users.append(admin)

    print(f"Creating {n_users} buyers and {n_sellers} sellers...")
    # Create sellers
    for _ in range(n_sellers):
        user = User(
            email=fake.unique.email(),
            first_name=fake.first_name(),
            last_name=fake.last_name(),
            address=fake.address(),
            is_seller=True
        )
        user.set_password(fake.password(length=12))
        users.append(user)

    # Create regular buyers
    for _ in range(n_users):
        user = User(
            email=fake.unique.email(),
            first_name=fake.first_name(),
            last_name=fake.last_name(),
            address=fake.address(),
            is_seller=False
        )
        user.set_password(fake.password(length=12))
        users.append(user)

    try:
        session.add_all(users)
        session.commit() # Commit to get user_ids
        print(f"Successfully created/retrieved {len(users)} users.")
        # Return all users from DB in case admin already existed
        return session.query(User).all()
    except SQLAlchemyError as e:
        session.rollback()
        print(f"Error creating users: {e}")
        return []


def create_categories(n):
    """Creates product categories."""
    ProductCategory = db_models['ProductCategory']
    categories = []
    # Check for default category (from create_database.sql)
    general_cat = session.query(ProductCategory).filter_by(category_name='General').first()
    if not general_cat:
        print("Creating default 'General' category...")
        general_cat = ProductCategory(category_name='General')
        session.add(general_cat)
        categories.append(general_cat) # Add to list to commit together

    print(f"Creating {n} product categories...")
    for _ in range(n):
        # Increase uniqueness attempts to prevent accidental duplicates
        for attempt in range(5):
            try:
                cat_name = fake.unique.bs().replace(" ", "-").capitalize() + "-Goods"
                category = ProductCategory(category_name=cat_name)
                categories.append(category)
                fake.unique.clear() # May need to clear after successful addition, or outside the loop
                break # Success, break retry loop
            except faker.exceptions.UniquenessException:
                if attempt == 4: # Last attempt failed
                     print(f"Warning: Could not generate unique name for category, skipping one category.")
                continue # Retry

    try:
        session.add_all(categories)
        session.commit()
        print(f"Successfully created/retrieved {len(categories)} categories.")
        return session.query(ProductCategory).all()
    except SQLAlchemyError as e:
        session.rollback()
        print(f"Error creating categories: {e}")
        return []

def create_products(categories, sellers, n_per_category):
    """Creates products for each category and assigns a seller."""
    Product = db_models['Product']
    products = []
    print(f"Creating {n_per_category} products for each category...")
    if not sellers:
        print("Error: Sellers are required to create products.")
        return []
    if not categories:
        print("Error: Categories are required to create products.")
        return []

    for category in categories:
        for _ in range(n_per_category):
            seller = random.choice(sellers)
            product = Product(
                category_id=category.category_id,
                product_name=fake.unique.catch_phrase(), # Use words that sound more like product names
                description=fake.text(max_nb_chars=200), # Limit description length
                price=round(random.uniform(5.0, 500.0), 2),
                owner_id=seller.user_id,
                image=fake.image_url(width=400, height=300) # Add image URL
            )
            products.append(product)
            try:
                fake.unique.clear() # Clear uniqueness cache
            except Exception: pass

    try:
        session.add_all(products)
        session.commit()
        print(f"Successfully created {len(products)} products.")
        return session.query(Product).all()
    except SQLAlchemyError as e:
        session.rollback()
        print(f"Error creating products: {e}")
        # Clear uniqueness to prevent errors in subsequent calls
        try: fake.unique.clear()
        except Exception: pass
        return []

def create_warehouses(n):
    """Creates warehouses."""
    Warehouse = db_models['Warehouse']
    warehouses = []
    print(f"Creating {n} warehouses...")
    for _ in range(n):
        # Use random integer coordinates as per project spec [cite: 11]
        warehouse = Warehouse(
            x=random.randint(0, 100),
            y=random.randint(0, 100),
            active=True
        )
        warehouses.append(warehouse)

    try:
        session.add_all(warehouses)
        session.commit()
        print(f"Successfully created {len(warehouses)} warehouses.")
        return session.query(Warehouse).all()
    except SQLAlchemyError as e:
        session.rollback()
        print(f"Error creating warehouses: {e}")
        return []

def create_inventory(products, warehouses, max_qty):
    """Adds product inventory to warehouses."""
    WarehouseProduct = db_models['WarehouseProduct']
    inventory_items = []
    print(f"Populating warehouses with inventory (max {max_qty} units/product)...")
    if not warehouses or not products:
        print("Error: Warehouses and products are required to create inventory.")
        return []

    for product in products:
        # Assign each product to a random number of warehouses
        num_warehouse_assignments = random.randint(1, min(3, len(warehouses)))
        assigned_warehouses = random.sample(warehouses, num_warehouse_assignments)
        for warehouse in assigned_warehouses:
            # Check if the record already exists
            existing_item = session.query(WarehouseProduct).filter_by(
                warehouse_id=warehouse.warehouse_id,
                product_id=product.product_id
            ).first()
            if not existing_item:
                 inventory_item = WarehouseProduct(
                    warehouse_id=warehouse.warehouse_id,
                    product_id=product.product_id,
                    quantity=random.randint(1, max_qty)
                )
                 inventory_items.append(inventory_item)
            else:
                # Option to update quantity or skip
                # Update quantity, ensuring it doesn't go below 1
                existing_item.quantity = max(1, existing_item.quantity + random.randint(-int(max_qty/2), max_qty))
                # No need to append, changes will be committed

    try:
        session.add_all(inventory_items) # Add only new items
        session.commit() # Commit new items and updates to existing ones
        print(f"Successfully created/updated {len(inventory_items)} inventory records (and potentially updated some existing ones).")
        # Return all inventory records, including potentially updated ones
        return session.query(WarehouseProduct).all()
    except SQLAlchemyError as e:
        session.rollback()
        print(f"Error creating inventory: {e}")
        return []

def create_carts_and_orders(users, products, n_orders_per_user, max_items):
    """Simulates users adding items to cart and creating orders."""
    Order = db_models['Order']
    OrderProduct = db_models['OrderProduct']
    Cart = db_models['Cart']
    orders_created = []
    buyers = [u for u in users if not u.is_seller]
    if not buyers or not products:
        print("Error: Buyers and products are required to create orders.")
        return []

    print(f"Creating up to {n_orders_per_user} orders for each buyer...")
    order_count = 0
    for buyer in buyers:
        # Ensure the user has a cart (if not created on login)
        cart = session.query(Cart).filter_by(user_id=buyer.user_id).first()
        if not cart:
            cart = Cart(user_id=buyer.user_id)
            session.add(cart)
            try:
                session.commit() # Need cart_id
            except SQLAlchemyError as e:
                 session.rollback()
                 print(f"Failed to create cart for user {buyer.user_id}: {e}")
                 continue # Skip this user

        orders_for_this_user = 0
        for _ in range(random.randint(1, n_orders_per_user)):
            if orders_for_this_user >= n_orders_per_user: break

            # 1. Simulate adding items to cart (if cart persistence needed)
            #    or directly generate order items
            num_items = random.randint(1, max_items)
            order_total = 0
            items_for_order = []
            product_ids_in_order = set() # Prevent duplicate products in the same order

            available_products = [p for p in products if p.owner_id != buyer.user_id] # Buyer can't buy their own products
            if not available_products: continue # Skip if no products available to buy

            for _ in range(num_items):
                if not available_products: break # Stop if all available products are added
                product = random.choice(available_products)
                if product.product_id in product_ids_in_order: continue # Skip duplicate product

                quantity = random.randint(1, 3) # Reduce quantity per item
                price = product.price # Price determined at time of addition
                order_total += price * quantity
                items_for_order.append({
                    'product_id': product.product_id,
                    'quantity': quantity,
                    'price': price,
                    'seller_id': product.owner_id
                })
                product_ids_in_order.add(product.product_id)
                available_products.remove(product) # Remove from available list for this order

            if not items_for_order: continue # Skip if no items were selected

            # 2. Create the order
            order = Order(
                buyer_id=buyer.user_id,
                total_amount=round(order_total, 2),
                num_products=sum(item['quantity'] for item in items_for_order),
                order_status='Unfulfilled' # Initial status
            )
            session.add(order)
            try:
                session.flush() # Get the order_id
            except SQLAlchemyError as e:
                session.rollback()
                print(f"Failed to create order for user {buyer.user_id} (flush): {e}")
                continue # Skip this order

            # 3. Create order items
            order_items_added = True
            for item_data in items_for_order:
                order_product = OrderProduct(
                    order_id=order.order_id,
                    product_id=item_data['product_id'],
                    quantity=item_data['quantity'],
                    price=item_data['price'],
                    seller_id=item_data['seller_id'],
                    status='Unfulfilled' # Initial status
                )
                session.add(order_product)

            # Commit each order and its items individually for robustness
            try:
                session.commit()
                orders_created.append(order)
                orders_for_this_user += 1
                order_count += 1
            except SQLAlchemyError as e:
                session.rollback()
                print(f"Failed to add order items or commit order {order.order_id if order else 'N/A'} for user {buyer.user_id}: {e}")


    print(f"Successfully created {order_count} orders.")
    # Query needs list of buyer_ids
    buyer_ids = [b.user_id for b in buyers]
    return session.query(Order).filter(Order.buyer_id.in_(buyer_ids)).all()

def create_shipments(orders, warehouses, n_shipments):
    """Creates shipments for a subset of orders."""
    Shipment = db_models['Shipment']
    ShipmentItem = db_models['ShipmentItem']
    OrderProduct = db_models['OrderProduct'] # Need to query order items
    shipments_created = []
    shipment_statuses = ['packing', 'packed', 'loading', 'loaded', 'delivering', 'delivered'] # [cite: 45]

    if not orders:
        print("No orders available to create shipments for.")
        return []
    if not warehouses:
        print("Error: Warehouses are required to create shipments.")
        return []

    # Randomly select from the available orders
    orders_to_ship = random.sample(orders, min(n_shipments, len(orders)))

    print(f"Attempting to create shipments for {len(orders_to_ship)} orders...")
    shipment_count = 0
    for order in orders_to_ship:
        # Check if a shipment already exists for this order
        existing_shipment = session.query(Shipment).filter_by(order_id=order.order_id).first()
        if existing_shipment:
            continue

        warehouse = random.choice(warehouses)
        # Random destination coordinates [cite: 11]
        dest_x = random.randint(0, 100)
        dest_y = random.randint(0, 100)
        status = random.choice(shipment_statuses)

        shipment = Shipment(
             order_id=order.order_id,
             warehouse_id=warehouse.warehouse_id,
             destination_x=dest_x,
             destination_y=dest_y,
             status=status,
             ups_tracking_id=fake.ean(length=13) if status != 'packing' else None, # Assign tracking ID only after packing
             truck_id=random.randint(1, 20) if status in ['loading', 'loaded', 'delivering', 'delivered'] else None # Assign truck ID only after loading
        )
        session.add(shipment)
        try:
            session.flush() # Get shipment_id
        except SQLAlchemyError as e:
             session.rollback()
             print(f"Failed to create shipment for order {order.order_id} (flush): {e}")
             continue # Skip this order

        # Create shipment items
        order_items = session.query(OrderProduct).filter_by(order_id=order.order_id).all()
        if not order_items:
            print(f"Warning: Order {order.order_id} has no items. Cannot create shipment items. Rolling back shipment creation.")
            session.rollback() # Rollback the shipment addition
            continue

        items_added = True
        for item in order_items:
             shipment_item = ShipmentItem(
                 shipment_id=shipment.shipment_id,
                 product_id=item.product_id,
                 quantity=item.quantity
             )
             session.add(shipment_item)

        # If status is 'delivered', update order status
        if status == 'delivered':
            order.order_status = 'Fulfilled'
            for item in order_items:
                item.status = 'Fulfilled'
                item.fulfillment_date = fake.past_datetime(start_date="-30d") # Set a past fulfillment date


        # Commit shipment and its items
        try:
            session.commit()
            shipments_created.append(shipment)
            shipment_count += 1
        except SQLAlchemyError as e:
             session.rollback()
             print(f"Failed to add shipment items or commit shipment for order {order.order_id}: {e}")


    print(f"Successfully created {shipment_count} shipments.")
    return shipments_created

# --- Main Execution Logic ---
if __name__ == "__main__":
    print("Starting database seeding...")

    # Check if there's already significant data to avoid over-populating
    user_count = session.query(db_models['User']).count()
    product_count = session.query(db_models['Product']).count()
    print(f"Current user count: {user_count}, Product count: {product_count}")

    if user_count > 10 and product_count > 20 : # Adjust check condition
        print(f"Database appears to have sufficient data already. Skipping seeding.")
        print("To force re-seeding, please manually clear the relevant tables first (e.g., using `psql` or a DB admin tool).")
    else:
        print("-" * 20)
        # 1. Create users
        all_users = create_users(NUM_USERS, NUM_SELLERS)
        sellers = [u for u in all_users if u.is_seller]
        print("-" * 20)

        # 2. Create categories
        all_categories = create_categories(NUM_CATEGORIES)
        print("-" * 20)

        # 3. Create products (ensure categories and sellers exist)
        all_products = []
        if all_categories and sellers:
             all_products = create_products(all_categories, sellers, NUM_PRODUCTS_PER_CATEGORY)
        else:
             print("Skipping product creation due to missing categories or sellers.")
        print("-" * 20)

        # 4. Create warehouses
        all_warehouses = create_warehouses(NUM_WAREHOUSES)
        print("-" * 20)

        # 5. Create inventory (ensure products and warehouses exist)
        if all_products and all_warehouses:
            create_inventory(all_products, all_warehouses, MAX_INITIAL_INVENTORY)
        else:
             print("Skipping inventory creation due to missing products or warehouses.")
        print("-" * 20)

        # 6. Create orders (ensure users and products exist)
        all_orders = []
        if all_users and all_products:
            all_orders = create_carts_and_orders(all_users, all_products, NUM_ORDERS_PER_USER, MAX_ITEMS_PER_ORDER)
        else:
            print("Skipping order creation due to missing users or products.")
        print("-" * 20)

        # 7. Create shipments (ensure orders and warehouses exist)
        if all_orders and all_warehouses:
             create_shipments(all_orders, all_warehouses, NUM_SHIPMENTS_TO_CREATE)
        else:
             print("Skipping shipment creation due to missing orders or warehouses.")
        print("-" * 20)

        print("Database seeding completed!")

    # Close the session
    session.close()
    engine.dispose()
    print("Database session closed.")