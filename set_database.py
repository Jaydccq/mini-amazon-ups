import os
import random
import sys
from datetime import datetime, timedelta
from faker import Faker
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError, OperationalError, IntegrityError

# --- Configuration ---
# Get database connection string from environment variable or use default
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:abc123@localhost:5432/mini_amazon')

# Increased data volume
NUM_USERS = 500         # Increased from 50
NUM_SELLERS = 50        # Increased from 5
NUM_CATEGORIES = 15      # Increased from 5
NUM_PRODUCTS_PER_CATEGORY = 40 # Increased from 20
NUM_WAREHOUSES = 20      # Increased from 10
MAX_INITIAL_INVENTORY = 250 # Increased from 100
NUM_ORDERS_PER_USER = 10    # Increased from 5
MAX_ITEMS_PER_ORDER = 6    # Increased from 5
# Adjust shipment calculation based on increased orders
TOTAL_ORDERS_ESTIMATE = NUM_USERS * NUM_ORDERS_PER_USER
NUM_SHIPMENTS_TO_CREATE = int(TOTAL_ORDERS_ESTIMATE * 0.85) # Assume 85% get a shipment
NUM_REVIEWS_TO_CREATE = int(TOTAL_ORDERS_ESTIMATE * 1.5) # Generate more reviews than orders

# --- Dynamically Import Application Models ---
project_root = os.path.dirname(os.path.abspath(__file__))
app_dir = os.path.join(project_root, 'app')
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)
    sys.path.insert(0, project_root)

try:
    # Try importing from app.model, including the Review model
    # ** IMPORTANT: Ensure WarehouseProduct in app.model has the new fields **
    from app.model import (
        db as imported_db, User, ProductCategory, Product, Warehouse,
        WarehouseProduct, Cart, CartProduct, Order, OrderProduct, Shipment,
        ShipmentItem, Review # Added Review model
    )
    db_models = {
        'User': User, 'ProductCategory': ProductCategory, 'Product': Product,
        'Warehouse': Warehouse, 'WarehouseProduct': WarehouseProduct, 'Cart': Cart,
        'CartProduct': CartProduct, 'Order': Order, 'OrderProduct': OrderProduct,
        'Shipment': Shipment, 'ShipmentItem': ShipmentItem, 'Review': Review # Added Review model
    }
except ImportError as e:
    print(f"Error: Could not import application models (including Review). Ensure the script's location is correct and dependencies/models exist.")
    print(f"Import Error: {e}")
    print(f"Current Python Path: {sys.path}")
    sys.exit(1)

# Initialize Faker
fake = Faker()

# --- Database Connection ---
try:
    engine = create_engine(DATABASE_URL)
    connection = engine.connect()
    connection.close()
    print(f"Successfully connected to database: {DATABASE_URL.split('@')[-1]}")
except OperationalError as e:
     print(f"Error: Could not connect to database {DATABASE_URL.split('@')[-1]}. Check connection string and DB status.")
     print(f"SQLAlchemy Error: {e}")
     sys.exit(1)
except Exception as e:
    print(f"An unknown error occurred while connecting to the database: {e}")
    sys.exit(1)

Session = sessionmaker(bind=engine)
session = Session()

# --- (Other functions like create_users, create_categories, etc. remain here) ---

def create_users(n_users, n_sellers):
    """Creates regular users and seller users, including default admin."""
    User = db_models['User']
    users_to_add = []
    existing_emails = {u.email for u in session.query(User.email).all()} # More efficient check

    # Ensure admin user exists
    admin_email = 'admin@example.com'
    if admin_email not in existing_emails:
        print("Creating default admin user...")
        admin = User(email=admin_email, first_name='Admin', last_name='User', is_seller=True)
        admin.set_password('admin')
        users_to_add.append(admin)
        existing_emails.add(admin_email)
    else:
        print("Default admin user already exists.")

    print(f"Attempting to create {n_sellers} sellers...")
    sellers_created = 0
    while sellers_created < n_sellers:
        email = fake.unique.email()
        if email in existing_emails:
            fake.unique.clear() # Clear uniqueness cache for email
            continue
        user = User(
            email=email,
            first_name=fake.first_name(),
            last_name=fake.last_name(),
            address=fake.address().replace('\n', ', '), # Format address
            is_seller=True,
            current_balance=round(random.uniform(500.0, 10000.0), 2) # Add balance
        )
        user.set_password(fake.password(length=12))
        users_to_add.append(user)
        existing_emails.add(email)
        sellers_created += 1
        if sellers_created % 10 == 0:
             print(f"  Created {sellers_created}/{n_sellers} sellers...")

    print(f"Attempting to create {n_users} buyers...")
    buyers_created = 0
    while buyers_created < n_users:
        email = fake.unique.email()
        if email in existing_emails:
            fake.unique.clear() # Clear uniqueness cache for email
            continue
        user = User(
            email=email,
            first_name=fake.first_name(),
            last_name=fake.last_name(),
            address=fake.address().replace('\n', ', '), # Format address
            is_seller=False,
            current_balance=round(random.uniform(50.0, 2000.0), 2) # Add balance
        )
        user.set_password(fake.password(length=12))
        users_to_add.append(user)
        existing_emails.add(email)
        buyers_created += 1
        if buyers_created % 50 == 0:
            print(f"  Created {buyers_created}/{n_users} buyers...")


    try:
        session.add_all(users_to_add)
        session.commit()
        print(f"Successfully created/retrieved {len(users_to_add)} new users.")
        # Return all users including pre-existing ones
        return session.query(User).all()
    except SQLAlchemyError as e:
        session.rollback()
        print(f"Error creating users: {e}")
        return [] # Return empty list on error

def create_categories(n):
    """Creates product categories with more variety."""
    ProductCategory = db_models['ProductCategory']
    categories_to_add = []
    existing_names = {c.category_name for c in session.query(ProductCategory.category_name).all()}

    # Ensure default category exists
    default_cat_name = 'General'
    if default_cat_name not in existing_names:
        print("Creating default 'General' category...")
        general_cat = ProductCategory(category_name=default_cat_name)
        categories_to_add.append(general_cat)
        existing_names.add(default_cat_name)
    else:
        print("Default 'General' category already exists.")

    print(f"Attempting to create {n} product categories...")
    base_categories = [
        'Electronics', 'Computers', 'Smart Home', 'Arts & Crafts', 'Automotive',
        'Baby', 'Beauty', 'Personal Care', "Women's Fashion", "Men's Fashion",
        'Girls\' Fashion', 'Boys\' Fashion', 'Health', 'Household', 'Home', 'Kitchen',
        'Industrial', 'Scientific', 'Luggage', 'Movies & TV', 'Music', 'CDs & Vinyl',
        'Pet Supplies', 'Software', 'Sports', 'Outdoors', 'Tools & Home Improvement',
        'Toys & Games', 'Video Games', 'Books'
    ]
    categories_created = 0
    while categories_created < n:
        cat_name = fake.unique.catch_phrase().title() # Use catchphrases for more variety
        if cat_name in existing_names:
             fake.unique.clear()
             continue

        # Optional: combine with a base category sometimes
        if random.random() < 0.3:
             cat_name = f"{random.choice(base_categories)} - {cat_name}"

        # Limit length if needed
        cat_name = cat_name[:99]

        if cat_name not in existing_names:
             category = ProductCategory(category_name=cat_name)
             categories_to_add.append(category)
             existing_names.add(cat_name)
             categories_created += 1
        else:
             fake.unique.clear() # Clear if generated name still conflicts

        if categories_created % 5 == 0 and categories_created > 0:
             print(f"  Created {categories_created}/{n} categories...")


    try:
        session.add_all(categories_to_add)
        session.commit()
        print(f"Successfully created {len(categories_to_add)} new categories.")
        return session.query(ProductCategory).all()
    except SQLAlchemyError as e:
        session.rollback()
        print(f"Error creating categories: {e}")
        return []

def create_products(categories, sellers, n_per_category):
    """Creates products with more descriptive text and varied pricing."""
    Product = db_models['Product']
    products_to_add = []
    existing_names = {p.product_name for p in session.query(Product.product_name).all()}

    if not sellers:
        print("Error: Sellers are required to create products.")
        return []
    if not categories:
        print("Error: Categories are required to create products.")
        return []

    print(f"Creating up to {n_per_category} products for each of {len(categories)} categories...")
    total_products_added = 0
    for category in categories:
        products_in_category = 0
        while products_in_category < n_per_category:
            seller = random.choice(sellers)
            # Generate more diverse product names
            base_name = fake.unique.bs().replace(" ", "-").capitalize()
            prod_name = f"{base_name} {fake.word().capitalize()} {random.choice(['Device', 'Kit', 'System', 'Gadget', 'Tool', 'Accessory', 'Set'])}"
            prod_name = prod_name[:99] # Ensure length constraint

            if prod_name in existing_names:
                fake.unique.clear()
                continue

            product = Product(
                category_id=category.category_id,
                product_name=prod_name,
                description=fake.paragraph(nb_sentences=random.randint(3, 7)), # Longer descriptions
                price=round(random.uniform(1.0, 2500.0) ** (1/random.uniform(1.1, 1.5)), 2), # More varied price distribution
                owner_id=seller.user_id,
                image=fake.image_url(width=600, height=400) # Larger image placeholder
            )
            products_to_add.append(product)
            existing_names.add(prod_name)
            products_in_category += 1
            total_products_added += 1

            if total_products_added % 100 == 0:
                 print(f"  Added {total_products_added} products so far...")

    try:
        session.add_all(products_to_add)
        session.commit()
        print(f"Successfully created {len(products_to_add)} products.")
        return session.query(Product).all()
    except SQLAlchemyError as e:
        session.rollback()
        print(f"Error creating products: {e}")
        try: fake.unique.clear()
        except Exception: pass
        return []

def create_warehouses(n):
    """Creates warehouses."""
    Warehouse = db_models['Warehouse']
    warehouses_to_add = []
    print(f"Creating {n} warehouses...")
    for i in range(n):
        warehouse = Warehouse(
            x=random.randint(0, 100),
            y=random.randint(0, 100),
            active=True # Assume all start active
        )
        warehouses_to_add.append(warehouse)
        if (i + 1) % 5 == 0:
             print(f"  Prepared {i+1}/{n} warehouses...")

    try:
        session.add_all(warehouses_to_add)
        session.commit()
        print(f"Successfully created {len(warehouses_to_add)} warehouses.")
        return session.query(Warehouse).all()
    except SQLAlchemyError as e:
        session.rollback()
        print(f"Error creating warehouses: {e}")
        return []

# --- MODIFIED FUNCTION ---
def create_inventory(products, warehouses, max_qty):
    """Adds or updates product inventory in warehouses with more details."""
    WarehouseProduct = db_models['WarehouseProduct']
    inventory_items_to_add = []
    inventory_items_to_update = 0
    inventory_updates_applied = [] # To track changes on existing items

    if not warehouses or not products:
        print("Error: Warehouses and products are required to create inventory.")
        return []

    print(f"Populating/updating inventory for {len(products)} products across {len(warehouses)} warehouses (max initial {max_qty} units/product)...")

    # Fetch existing inventory to avoid redundant queries inside loop
    existing_inventory = {}
    for item in session.query(WarehouseProduct).all():
         existing_inventory[(item.warehouse_id, item.product_id)] = item

    product_count = 0
    for product in products:
        # Assign each product to a random number of warehouses (e.g., 1 to 5)
        num_warehouse_assignments = random.randint(1, min(5, len(warehouses)))
        assigned_warehouses = random.sample(warehouses, num_warehouse_assignments)

        for warehouse in assigned_warehouses:
            key = (warehouse.warehouse_id, product.product_id)

            # --- New Fields Data Generation ---
            current_time = datetime.now()
            last_restock = fake.date_time_between(start_date="-90d", end_date="now", tzinfo=None) # Restocked in last 3 months
            # Cost price as a percentage of product price (e.g., 50-80%)
            cost = round(product.price * random.uniform(0.5, 0.8), 2)
            # Simple shelf location format
            aisle = random.randint(1, 20)
            shelf_letter = random.choice('ABCDEFG')
            shelf_number = random.randint(1, 10)
            location = f"A{aisle}S{shelf_letter}-{shelf_number}"
            # Inventory status - mostly available, sometimes reserved or damaged
            status = random.choices(['Available', 'Reserved', 'Damaged'], weights=[0.95, 0.03, 0.02])[0]
            quantity = random.randint(1, max_qty) if status == 'Available' else random.randint(0, int(max_qty * 0.1)) # Lower qty if not available

            if key not in existing_inventory:
                 # Add new inventory record with detailed info
                 inventory_item = WarehouseProduct(
                    warehouse_id=warehouse.warehouse_id,
                    product_id=product.product_id,
                    quantity=quantity,
                    # --- Add new fields ---
                    last_restock_date=last_restock,
                    cost_price=cost,
                    shelf_location=location,
                    status=status
                 )
                 inventory_items_to_add.append(inventory_item)
                 # Add to cache to prevent duplicates within this run
                 existing_inventory[key] = inventory_item
            else:
                 # Update existing inventory record (potentially changing all fields)
                 existing_item = existing_inventory[key]

                 # Decide whether to update based on random chance or logic (e.g., recent restock)
                 if random.random() < 0.25: # ~25% chance to update an existing record's details
                    change = random.randint(-int(existing_item.quantity * 0.3), int(max_qty * 0.5)) # Allow reduction
                    existing_item.quantity = max(0, existing_item.quantity + change) # Allow stock to go to 0
                    existing_item.last_restock_date = last_restock # Update restock date on change
                    existing_item.cost_price = cost # Update cost (maybe price changed)
                    existing_item.shelf_location = location # Maybe it moved
                    existing_item.status = status # Status might change
                    inventory_items_to_update += 1
                    inventory_updates_applied.append(existing_item) # Track for logging/debugging if needed

        product_count += 1
        if product_count % 100 == 0:
             print(f"  Processed inventory for {product_count}/{len(products)} products...")

    try:
        if inventory_items_to_add:
             session.add_all(inventory_items_to_add)
        # Updates to existing items are tracked by the session automatically if they were fetched from it
        session.commit()
        print(f"Successfully created {len(inventory_items_to_add)} new inventory records and initiated updates for {inventory_items_to_update} existing records.")
        # Return all inventory records (new and existing/updated)
        return session.query(WarehouseProduct).all()
    except SQLAlchemyError as e:
        session.rollback()
        print(f"Error creating/updating inventory: {e}")
        return []

# --- (Rest of the functions: create_carts_and_orders, create_shipments, create_reviews) ---

def create_carts_and_orders(users, products, n_orders_per_user, max_items):
    """Simulates users adding items to cart and creating orders with varied dates."""
    Order = db_models['Order']
    OrderProduct = db_models['OrderProduct']
    Cart = db_models['Cart']
    User = db_models['User']

    orders_created_list = []
    buyers = [u for u in users if not u.is_seller]
    if not buyers or not products:
        print("Error: Buyers and products are required to create orders.")
        return []

    print(f"Creating up to {n_orders_per_user} orders for each of {len(buyers)} buyers...")
    total_order_count = 0
    buyer_count = 0

    # Pre-fetch carts to reduce queries
    existing_carts = {cart.user_id: cart for cart in session.query(Cart).filter(Cart.user_id.in_([b.user_id for b in buyers])).all()}

    for buyer in buyers:
        buyer_count += 1
        if buyer_count % 50 == 0:
             print(f"  Processing orders for buyer {buyer_count}/{len(buyers)}...")

        # Get or create cart
        cart = existing_carts.get(buyer.user_id)
        if not cart:
            cart = Cart(user_id=buyer.user_id)
            session.add(cart)
            try:
                session.flush() # Need cart_id before commit for potential use
                existing_carts[buyer.user_id] = cart
            except SQLAlchemyError as e:
                 session.rollback()
                 print(f"Failed to create cart for user {buyer.user_id}: {e}")
                 continue # Skip this user

        orders_for_this_user = 0
        for _ in range(random.randint(0, n_orders_per_user)): # Allow 0 orders
            if orders_for_this_user >= n_orders_per_user: break

            num_items_in_order = random.randint(1, max_items)
            order_total = 0
            items_for_order = []
            product_ids_in_order = set()

            # Ensure buyer doesn't buy their own products if they were mistakenly also a seller
            available_products = [p for p in products if p.owner_id != buyer.user_id]
            if not available_products: continue

            for _ in range(num_items_in_order):
                if not available_products: break
                product = random.choice(available_products)
                if product.product_id in product_ids_in_order: continue

                quantity = random.randint(1, 4) # Slightly higher max quantity
                price = product.price # Price at time of order
                order_total += price * quantity
                items_for_order.append({
                    'product_id': product.product_id,
                    'quantity': quantity,
                    'price': price,
                    'seller_id': product.owner_id
                })
                product_ids_in_order.add(product.product_id)
                # Simulate removing product from available pool for this order attempt
                # Note: This doesn't prevent the *same* product being chosen by another concurrent process or even the next iteration if available_products is large.
                # For true stock checking, you'd need to query and lock inventory, which is beyond this script's scope.
                # available_products.remove(product) # Removing can be slow on large lists, consider alternatives if performance matters

            if not items_for_order: continue

            # Simulate order date (past year)
            order_date = fake.date_time_between(start_date="-1y", end_date="now", tzinfo=None)

            order = Order(
                buyer_id=buyer.user_id,
                total_amount=round(order_total, 2),
                num_products=sum(item['quantity'] for item in items_for_order),
                order_status='Unfulfilled', # Default status
                order_date=order_date # Set the historical date
            )
            session.add(order)
            try:
                session.flush() # Get the order_id
            except SQLAlchemyError as e:
                session.rollback()
                print(f"Failed to create order for user {buyer.user_id} (flush): {e}")
                continue

            # Create order items
            order_items_to_add = []
            for item_data in items_for_order:
                order_product = OrderProduct(
                    order_id=order.order_id,
                    product_id=item_data['product_id'],
                    quantity=item_data['quantity'],
                    price=item_data['price'],
                    seller_id=item_data['seller_id'],
                    status='Unfulfilled' # Default status
                )
                order_items_to_add.append(order_product)

            session.add_all(order_items_to_add)

            # Commit each order individually
            try:
                session.commit()
                orders_created_list.append(order)
                orders_for_this_user += 1
                total_order_count += 1
            except IntegrityError as e: # Catch potential duplicate key errors if logic allows
                 session.rollback()
                 print(f"Failed to add order items (IntegrityError) for order {order.order_id}: {e}")
            except SQLAlchemyError as e:
                session.rollback()
                print(f"Failed to commit order {order.order_id} for user {buyer.user_id}: {e}")

    print(f"Successfully created {total_order_count} orders.")
    # Return all orders created in this run
    return orders_created_list # Return list of created orders


def create_shipments(orders, warehouses, n_shipments_to_create):
    """Creates shipments for a subset of orders with varied statuses and timings."""
    Shipment = db_models['Shipment']
    ShipmentItem = db_models['ShipmentItem']
    OrderProduct = db_models['OrderProduct']
    Order = db_models['Order']

    shipments_created_list = []
    # shipment_statuses = ['packing', 'packed', 'loading', 'loaded', 'delivering', 'delivered']
    # Statuses will be determined based on order date and random chance

    if not orders:
        print("No orders available to create shipments for.")
        return []
    if not warehouses:
        print("Error: Warehouses are required to create shipments.")
        return []

    # Filter orders that might need shipment (e.g., Unfulfilled)
    unfulfilled_orders = [o for o in orders if o.order_status == 'Unfulfilled']

    # If fewer unfulfilled orders than desired shipments, sample from all orders provided
    if len(unfulfilled_orders) < n_shipments_to_create:
        orders_to_ship_from = orders
    else:
        orders_to_ship_from = unfulfilled_orders

    # Ensure we don't try to sample more orders than available
    num_to_sample = min(n_shipments_to_create, len(orders_to_ship_from))
    if num_to_sample <= 0:
        print("No suitable orders found to create shipments.")
        return []

    orders_for_shipment = random.sample(orders_to_ship_from, num_to_sample)

    print(f"Attempting to create shipments for {len(orders_for_shipment)} orders...")
    shipment_count = 0
    processed_orders = set() # Keep track of orders processed in this run

    for order in orders_for_shipment:
        if order.order_id in processed_orders: continue # Skip if already processed

        # Check if a shipment already exists for this order (robustness)
        existing_shipment = session.query(Shipment).filter_by(order_id=order.order_id).first()
        if existing_shipment:
            processed_orders.add(order.order_id)
            continue

        warehouse = random.choice(warehouses)
        dest_x = random.randint(0, 100)
        dest_y = random.randint(0, 100)

        # Determine status based on order date and randomness
        now = datetime.now()
        # Ensure order_date is offset-naive if 'now' is offset-naive
        order_date_naive = order.order_date.replace(tzinfo=None) if order.order_date.tzinfo else order.order_date
        days_since_order = (now - order_date_naive).days
        status = 'packing' # Default
        ups_tracking_id = None
        truck_id = None
        fulfillment_date = None

        if days_since_order > 30 and random.random() < 0.95: # Older orders likely delivered
             status = 'delivered'
        elif days_since_order > 10 and random.random() < 0.8: # Medium age, likely delivering/loaded
            status = random.choice(['delivering', 'loaded'])
        elif days_since_order > 2 and random.random() < 0.7: # Newer, likely packed/loading
            status = random.choice(['packed', 'loading'])
        # Otherwise stays 'packing'

        if status != 'packing':
             ups_tracking_id = fake.ean(length=13) # Use ean for tracking id like format
        if status in ['loading', 'loaded', 'delivering', 'delivered']:
             truck_id = random.randint(1, 50) # More trucks available
        if status == 'delivered':
             # Set fulfillment date somewhere between order date + 1 day and now
             min_fulfill_date = order_date_naive + timedelta(days=1)
             if min_fulfill_date < now:
                 fulfillment_date = fake.date_time_between(start_date=min_fulfill_date, end_date=now, tzinfo=None)
             else:
                 fulfillment_date = now # If order placed very recently but marked delivered

        shipment = Shipment(
             order_id=order.order_id,
             warehouse_id=warehouse.warehouse_id,
             destination_x=dest_x,
             destination_y=dest_y,
             status=status,
             ups_tracking_id=ups_tracking_id,
             truck_id=truck_id
        )
        session.add(shipment)
        try:
            session.flush() # Get shipment_id
        except SQLAlchemyError as e:
             session.rollback()
             print(f"Failed to create shipment for order {order.order_id} (flush): {e}")
             continue

        # Create shipment items
        order_items = session.query(OrderProduct).filter_by(order_id=order.order_id).all()
        if not order_items:
            print(f"Warning: Order {order.order_id} has no items. Cannot create shipment items. Rolling back shipment creation.")
            session.rollback()
            continue

        shipment_items_to_add = []
        for item in order_items:
             shipment_item = ShipmentItem(
                 shipment_id=shipment.shipment_id,
                 product_id=item.product_id,
                 quantity=item.quantity
             )
             shipment_items_to_add.append(shipment_item)
        session.add_all(shipment_items_to_add)

        # If status is 'delivered', update associated order and order items
        if status == 'delivered':
            try:
                 # Find the order in the session or query it
                 order_to_update = session.get(Order, order.order_id) # Use session.get for primary key lookup
                 if order_to_update:
                     order_to_update.order_status = 'Fulfilled'
                     # Update related order items
                     for item in order_items:
                         item_to_update = session.get(OrderProduct, item.id) # Assuming OrderProduct has a primary key 'id'
                         if item_to_update:
                             item_to_update.status = 'Fulfilled'
                             item_to_update.fulfillment_date = fulfillment_date
                 else:
                      print(f"Warning: Could not find order {order.order_id} in session to mark as Fulfilled.")

            except Exception as e:
                 # This might happen if the Order or OrderProduct models don't match expectations (e.g., no 'id' PK)
                 print(f"Error updating order/item status for delivered shipment {shipment.shipment_id}: {e}")
                 # Decide whether to rollback or just log the warning
                 # session.rollback() # Optional: Rollback if updating status is critical
                 # continue

        # Commit shipment and its items (and potential status updates)
        try:
            session.commit()
            shipments_created_list.append(shipment)
            shipment_count += 1
            processed_orders.add(order.order_id)
        except SQLAlchemyError as e:
             session.rollback()
             print(f"Failed to add shipment items or commit shipment for order {order.order_id}: {e}")

    print(f"Successfully created {shipment_count} shipments.")
    return shipments_created_list

# --- NEW: Review Generation Function ---
def create_reviews(users, products, n_reviews_to_create):
    """Creates reviews for products and sellers."""
    Review = db_models['Review']
    reviews_to_add = []
    buyers = [u for u in users if not u.is_seller]
    sellers = [u for u in users if u.is_seller]

    if not buyers or not products:
        print("Error: Buyers and products are required to create reviews.")
        return []

    print(f"Attempting to create {n_reviews_to_create} reviews...")
    reviews_created = 0

    # Keep track of existing reviews to avoid duplicates (user, product) or (user, seller)
    existing_product_reviews = {(r.user_id, r.product_id) for r in session.query(Review.user_id, Review.product_id).filter(Review.product_id != None).all()}
    existing_seller_reviews = {(r.user_id, r.seller_id) for r in session.query(Review.user_id, Review.seller_id).filter(Review.seller_id != None).all()}

    # Generate reviews iteratively
    attempts = 0
    max_attempts = n_reviews_to_create * 3 # Set a limit to prevent infinite loops if collisions are high

    while reviews_created < n_reviews_to_create and attempts < max_attempts:
        attempts += 1
        reviewer = random.choice(buyers)
        review_target_type = random.choice(['product', 'seller'])

        if review_target_type == 'product' and products:
            target_product = random.choice(products)
            target_key = (reviewer.user_id, target_product.product_id)
            if target_key in existing_product_reviews: continue # Avoid duplicate review

            review = Review(
                user_id=reviewer.user_id,
                product_id=target_product.product_id,
                seller_id=None,
                rating=random.choices([1, 2, 3, 4, 5], weights=[0.05, 0.1, 0.2, 0.4, 0.25])[0], # Weighted ratings
                comment=fake.paragraph(nb_sentences=random.randint(1, 4)),
                review_date=fake.date_time_between(start_date="-6m", end_date="now", tzinfo=None) # Reviews from last 6 months
            )
            reviews_to_add.append(review)
            existing_product_reviews.add(target_key)
            reviews_created += 1

        elif review_target_type == 'seller' and sellers:
            target_seller = random.choice(sellers)
            # Ensure reviewer is not the seller themselves
            if reviewer.user_id == target_seller.user_id: continue

            target_key = (reviewer.user_id, target_seller.user_id)
            if target_key in existing_seller_reviews: continue # Avoid duplicate review

            review = Review(
                user_id=reviewer.user_id,
                product_id=None,
                seller_id=target_seller.user_id,
                rating=random.choices([1, 2, 3, 4, 5], weights=[0.08, 0.12, 0.2, 0.35, 0.25])[0], # Slightly different weights for sellers
                comment=fake.paragraph(nb_sentences=random.randint(1, 3)),
                review_date=fake.date_time_between(start_date="-6m", end_date="now", tzinfo=None)
            )
            reviews_to_add.append(review)
            existing_seller_reviews.add(target_key)
            reviews_created += 1

        if reviews_created % 200 == 0 and reviews_created > 0 and len(reviews_to_add) > 0: # Only print if count increased
             print(f"  Prepared {reviews_created}/{n_reviews_to_create} reviews...")

        # Add reviews in batches to avoid large transactions
        if len(reviews_to_add) >= 500:
            try:
                 session.add_all(reviews_to_add)
                 session.commit()
                 print(f"  Committed batch of {len(reviews_to_add)} reviews.")
                 reviews_to_add = [] # Reset batch
            except IntegrityError as e: # Catch potential unique constraint violations if model enforces them
                 session.rollback()
                 print(f"Error creating reviews batch (IntegrityError likely duplicate): {e}")
                 # Clear the batch and potentially re-fetch existing reviews to update the sets
                 reviews_to_add = []
                 existing_product_reviews.update({(r.user_id, r.product_id) for r in session.query(Review.user_id, Review.product_id).filter(Review.product_id != None).all()})
                 existing_seller_reviews.update({(r.user_id, r.seller_id) for r in session.query(Review.user_id, Review.seller_id).filter(Review.seller_id != None).all()})
            except SQLAlchemyError as e:
                session.rollback()
                print(f"Error creating reviews batch: {e}")
                # If batch commit fails, clear the list to avoid retrying same faulty data
                reviews_to_add = []

    # Commit any remaining reviews
    if reviews_to_add:
        try:
            session.add_all(reviews_to_add)
            session.commit()
            print(f"  Committed final batch of {len(reviews_to_add)} reviews.")
        except IntegrityError as e:
            session.rollback()
            print(f"Error creating final reviews batch (IntegrityError likely duplicate): {e}")
        except SQLAlchemyError as e:
            session.rollback()
            print(f"Error creating final reviews batch: {e}")

    if attempts >= max_attempts and reviews_created < n_reviews_to_create:
        print(f"Warning: Reached max attempts ({max_attempts}) but only created {reviews_created}/{n_reviews_to_create} reviews. Might indicate high collision rate or issues finding unique review targets.")

    print(f"Successfully attempted to create reviews. Final count in DB will reflect committed entries.")
    # Return the actual count from DB for confirmation
    final_count = session.query(func.count(Review.review_id)).scalar()
    print(f"Current total reviews in DB: {final_count}")
    return final_count


# --- Main Execution Logic ---
if __name__ == "__main__":
    print("Starting database seeding...")

    # Check if there's already significant data
    user_count = session.query(func.count(db_models['User'].user_id)).scalar()
    product_count = session.query(func.count(db_models['Product'].product_id)).scalar()
    order_count = session.query(func.count(db_models['Order'].order_id)).scalar()
    review_count = session.query(func.count(db_models['Review'].review_id)).scalar()
    inventory_count = session.query(func.count(db_models['WarehouseProduct'].id)).scalar() # Check inventory too

    print(f"Current counts - Users: {user_count}, Products: {product_count}, Orders: {order_count}, Reviews: {review_count}, Inventory Items: {inventory_count}")

    # Adjust threshold for skipping based on increased target numbers
    # Increase threshold slightly to encourage re-running if needed
    if user_count > NUM_USERS * 0.8 and product_count > (NUM_CATEGORIES * NUM_PRODUCTS_PER_CATEGORY * 0.8) and order_count > (NUM_USERS * NUM_ORDERS_PER_USER * 0.5):
        print(f"Database appears to have significant data already. Skipping full seeding run.")
        # Optionally, run only specific parts like updating inventory or adding reviews
        # print("Consider running specific functions if you only need to add/update certain data.")
        # Example: only update inventory
        # print("-" * 20)
        # print("Attempting to update existing inventory...")
        # all_products_existing = session.query(Product).all()
        # all_warehouses_existing = session.query(Warehouse).all()
        # if all_products_existing and all_warehouses_existing:
        #      create_inventory(all_products_existing, all_warehouses_existing, MAX_INITIAL_INVENTORY)
        #      print(f"Total inventory records in DB after update: {session.query(func.count(db_models['WarehouseProduct'].id)).scalar()}")
        # else:
        #      print("Skipping inventory update due to missing products or warehouses.")
        # print("-" * 20)

    else:
        print("Proceeding with full data seeding...")
        print("-" * 20)
        # 1. Create users
        all_users = create_users(NUM_USERS, NUM_SELLERS)
        sellers = [u for u in all_users if u.is_seller]
        print(f"Total users in DB after creation/fetch: {session.query(func.count(db_models['User'].user_id)).scalar()}")
        print("-" * 20)

        # 2. Create categories
        all_categories = create_categories(NUM_CATEGORIES)
        print(f"Total categories in DB after creation/fetch: {session.query(func.count(db_models['ProductCategory'].category_id)).scalar()}")
        print("-" * 20)

        # 3. Create products
        all_products = []
        if all_categories and sellers:
             all_products = create_products(all_categories, sellers, NUM_PRODUCTS_PER_CATEGORY)
             print(f"Total products in DB after creation: {session.query(func.count(db_models['Product'].product_id)).scalar()}")
        else:
             print("Skipping product creation due to missing categories or sellers.")
        print("-" * 20)

        # 4. Create warehouses
        all_warehouses = create_warehouses(NUM_WAREHOUSES)
        print(f"Total warehouses in DB after creation: {session.query(func.count(db_models['Warehouse'].warehouse_id)).scalar()}")
        print("-" * 20)

        # 5. Create inventory (Uses the modified function)
        if all_products and all_warehouses:
            create_inventory(all_products, all_warehouses, MAX_INITIAL_INVENTORY)
            print(f"Total inventory records in DB after creation/update: {session.query(func.count(db_models['WarehouseProduct'].id)).scalar()}")
        else:
             print("Skipping inventory creation due to missing products or warehouses.")
        print("-" * 20)

        # 6. Create orders (ensure users and products exist)
        created_orders = []
        if all_users and all_products:
            # Pass only newly created products if you want orders only for them,
            # or pass all_products if orders can be for any product in DB
            created_orders = create_carts_and_orders(all_users, all_products, NUM_ORDERS_PER_USER, MAX_ITEMS_PER_ORDER)
            print(f"Total orders in DB after creation: {session.query(func.count(db_models['Order'].order_id)).scalar()}")
        else:
            print("Skipping order creation due to missing users or products.")
        print("-" * 20)

        # 7. Create shipments (ensure orders and warehouses exist)
        # Fetch *all* orders from DB now to include any potentially pre-existing ones for shipment creation
        all_db_orders = session.query(Order).all()
        if all_db_orders and all_warehouses:
             create_shipments(all_db_orders, all_warehouses, NUM_SHIPMENTS_TO_CREATE)
             print(f"Total shipments in DB after creation: {session.query(func.count(db_models['Shipment'].shipment_id)).scalar()}")
        else:
             print("Skipping shipment creation due to missing orders or warehouses.")
        print("-" * 20)

        # 8. Create reviews (ensure users and products exist) - NEW STEP
        if all_users and all_products:
            # Pass all users and products found/created
            create_reviews(all_users, all_products, NUM_REVIEWS_TO_CREATE)
            # Final count is printed within the function now
        else:
            print("Skipping review creation due to missing users or products.")
        print("-" * 20)

        print("Database seeding completed!")

    # Close the session
    session.close()
    engine.dispose()
    print("Database session closed.")