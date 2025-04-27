import os
import random
import sys
from datetime import datetime, timedelta
from faker import Faker
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError, OperationalError, IntegrityError

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:abc123@localhost:5432/mini_amazon')

NUM_USERS = 100        
NUM_SELLERS =30        
NUM_CATEGORIES = 8      
NUM_PRODUCTS_PER_CATEGORY = 15
NUM_WAREHOUSES = 5       
MAX_INITIAL_INVENTORY = 100 
NUM_ORDERS_PER_USER = 3    
MAX_ITEMS_PER_ORDER = 5     
TOTAL_ORDERS_ESTIMATE = NUM_USERS * NUM_ORDERS_PER_USER
NUM_SHIPMENTS_TO_CREATE = int(TOTAL_ORDERS_ESTIMATE * 0.85)
NUM_REVIEWS_TO_CREATE = int(TOTAL_ORDERS_ESTIMATE * 1.2) 
MIN_SELLERS_PER_PRODUCT = 2
NUM_ORDERS_ESTIMATE = NUM_USERS * NUM_ORDERS_PER_USER
project_root = os.path.dirname(os.path.abspath(__file__))
app_dir = os.path.join(project_root, 'app')
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)
    sys.path.insert(0, project_root)

try:
    from app.model import (
        db as imported_db, User, ProductCategory, Product, Warehouse,
        WarehouseProduct, Cart, CartProduct, Order, OrderProduct, Shipment,
        ShipmentItem, Review, Inventory
    )
    db_models = {
        'User': User, 'ProductCategory': ProductCategory, 'Product': Product,
        'Warehouse': Warehouse, 'WarehouseProduct': WarehouseProduct, 'Cart': Cart,
        'CartProduct': CartProduct, 'Order': Order, 'OrderProduct': OrderProduct,
        'Shipment': Shipment, 'ShipmentItem': ShipmentItem, 'Review': Review,
        'Inventory': Inventory
    }
except ImportError as e:
    print(f"Error: Could not import application models (including Inventory). Ensure the script's location is correct and dependencies/models exist.")
    print(f"Import Error: {e}")
    print(f"Current Python Path: {sys.path}")
    sys.exit(1)

fake = Faker()

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

def create_users(n_users, n_sellers):
    User = db_models['User']
    users_to_add = []
    existing_emails = {u.email for u in session.query(User.email).all()}

    admin_email = 'admin@example.com'
    if admin_email not in existing_emails:
        print("Creating default admin user...")
        admin = User(email=admin_email, first_name='Admin', last_name='User', is_seller=True)
        admin.set_password('admin')
        users_to_add.append(admin)
        existing_emails.add(admin_email)
    else:
        admin = session.query(User).filter_by(email=admin_email).first()
        if admin:
            print("Default admin user already exists.")
        else:
             print("WARN: Admin email exists in query but user object not found. Re-creating.")
             admin = User(email=admin_email, first_name='Admin', last_name='User', is_seller=True)
             admin.set_password('admin')
             users_to_add.append(admin)
             existing_emails.add(admin_email)

    print(f"Attempting to create {n_sellers} sellers...")
    sellers_created = 0
    while sellers_created < n_sellers:
        current_seller_count = session.query(func.count(User.user_id)).filter(User.is_seller == True).scalar()
        if current_seller_count >= n_sellers + 1:
             print("Required number of sellers already exist.")
             break

        email = fake.unique.email()
        if email in existing_emails:
            fake.unique.clear()
            continue
        user = User(
            email=email,
            first_name=fake.first_name(),
            last_name=fake.last_name(),
            address=fake.address().replace('\n', ', '),
            is_seller=True,
            current_balance=round(random.uniform(500.0, 10000.0), 2)
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
            fake.unique.clear()
            continue
        user = User(
            email=email,
            first_name=fake.first_name(),
            last_name=fake.last_name(),
            address=fake.address().replace('\n', ', '),
            is_seller=False,
            current_balance=round(random.uniform(50.0, 2000.0), 2)
        )
        user.set_password(fake.password(length=12))
        users_to_add.append(user)
        existing_emails.add(email)
        buyers_created += 1
        if buyers_created % 50 == 0:
            print(f"  Created {buyers_created}/{n_users} buyers...")

    try:
        session.add_all([u for u in users_to_add if u not in session])
        session.commit()
        print(f"Successfully ensured required number of users exist.")
        return session.query(User).all()
    except SQLAlchemyError as e:
        session.rollback()
        print(f"Error creating users: {e}")
        return []

def create_categories(n):
    ProductCategory = db_models['ProductCategory']
    categories_to_add = []
    existing_names = {c.category_name for c in session.query(ProductCategory.category_name).all()}

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
        cat_name = fake.unique.catch_phrase().title()
        if random.random() < 0.3:
             base = random.choice(base_categories)
             combined_name = f"{base} - {cat_name}"
             cat_name = combined_name[:99]

        if cat_name in existing_names:
             fake.unique.clear()
             continue

        category = ProductCategory(category_name=cat_name)
        categories_to_add.append(category)
        existing_names.add(cat_name)
        categories_created += 1

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
        attempt_limit = n_per_category * 3
        attempts = 0
        while products_in_category < n_per_category and attempts < attempt_limit:
            attempts += 1
            seller = random.choice(sellers)
            base_name = fake.unique.bs().replace(" ", "-").capitalize()
            prod_name = f"{base_name} {fake.word().capitalize()} {random.choice(['Device', 'Kit', 'System', 'Gadget', 'Tool', 'Accessory', 'Set'])}"
            prod_name = prod_name[:99] 

            if prod_name in existing_names:
                fake.unique.clear()
                continue

            price = round(random.paretovariate(1.5) * random.uniform(5, 50), 2)
            price = max(0.99, min(price, 5000.0))
            image=f"https://picsum.photos/seed/{prod_name.replace(' ', '_')}/400/300"

            product = Product(
                category_id=category.category_id,
                product_name=prod_name,
                description=fake.paragraph(nb_sentences=random.randint(3, 7)),
                price=price,
                owner_id=seller.user_id,
                image=image,
            )
            products_to_add.append(product)
            existing_names.add(prod_name)
            products_in_category += 1
            total_products_added += 1

            if total_products_added % 100 == 0:
                 print(f"  Added {total_products_added} products so far...")

        if attempts >= attempt_limit:
             print(f"Warning: Reached attempt limit for category '{category.category_name}', created {products_in_category}/{n_per_category} products.")

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
    Warehouse = db_models['Warehouse']
    warehouses_to_add = []
    print(f"Creating {n} warehouses...")
    for i in range(n):
        warehouse = Warehouse(
            x=random.randint(0, 100),
            y=random.randint(0, 100),
            active=True 
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

def create_warehouse_inventory(products, warehouses, default_max_qty):
    WarehouseProduct = db_models['WarehouseProduct']
    inventory_items_to_add = []
    inventory_items_to_update = 0

    if not warehouses or not products:
        print("Error: Warehouses and products are required to create warehouse inventory.")
        return []

    print(f"Populating/updating WAREHOUSE inventory for {len(products)} products...")

    existing_inventory = {}
    for item in session.query(WarehouseProduct).all():
         existing_inventory[(item.warehouse_id, item.product_id)] = item

    product_count = 0
    product_warehouse_map = {}  # To track which warehouses have which products
    
    for product in products:
        product_count += 1
        
        if len(warehouses) > 1:
            num_warehouse_assignments = random.randint(max(1, len(warehouses)//2), len(warehouses))
            assigned_warehouses = random.sample(warehouses, num_warehouse_assignments)
        else:
            assigned_warehouses = warehouses.copy()
        
        product_warehouse_map[product.product_id] = [w.warehouse_id for w in assigned_warehouses]
        
        total_qty_needed = max(100, 50 * len(assigned_warehouses))
        qty_per_warehouse = max(20, int(total_qty_needed / len(assigned_warehouses)))
        
        for warehouse in assigned_warehouses:
            key = (warehouse.warehouse_id, product.product_id)
            quantity = random.randint(qty_per_warehouse, qty_per_warehouse * 2)

            if key not in existing_inventory:
                 inventory_item = WarehouseProduct(
                    warehouse_id=warehouse.warehouse_id,
                    product_id=product.product_id,
                    quantity=quantity
                 )
                 inventory_items_to_add.append(inventory_item)
                 existing_inventory[key] = inventory_item
            else:
                 existing_item = existing_inventory[key]
                 existing_item.quantity = max(existing_item.quantity, quantity)
                 inventory_items_to_update += 1

        if product_count % 100 == 0:
             print(f"  Processed warehouse inventory for {product_count}/{len(products)} products...")

    try:
        if products:
            test_product = products[0]
            print(f"Setting high warehouse inventory for test product ID {test_product.product_id}")
            for warehouse in warehouses:
                key = (warehouse.warehouse_id, test_product.product_id)
                if key not in existing_inventory:
                    inventory_item = WarehouseProduct(
                        warehouse_id=warehouse.warehouse_id,
                        product_id=test_product.product_id,
                        quantity=200
                    )
                    inventory_items_to_add.append(inventory_item)
                    product_warehouse_map.setdefault(test_product.product_id, []).append(warehouse.warehouse_id)
                else:
                    existing_inventory[key].quantity = 200
                    if test_product.product_id not in product_warehouse_map:
                        product_warehouse_map[test_product.product_id] = []
                    if warehouse.warehouse_id not in product_warehouse_map[test_product.product_id]:
                        product_warehouse_map[test_product.product_id].append(warehouse.warehouse_id)
    except Exception as e:
        print(f"Error setting high warehouse inventory for test product: {e}")

    try:
        if inventory_items_to_add:
             session.add_all(inventory_items_to_add)
        session.commit()
        print(f"Successfully created {len(inventory_items_to_add)} new WAREHOUSE inventory records and updated {inventory_items_to_update} existing records.")
        return product_warehouse_map
    except SQLAlchemyError as e:
        session.rollback()
        print(f"Error creating/updating warehouse inventory: {e}")
        return {}

def create_seller_inventory(products, sellers, min_sellers_per_prod, product_warehouse_map, warehouses):
    Inventory = db_models['Inventory']
    inventory_items_to_add = []

    if not products or not sellers:
        print("Error: Products and sellers are required to create seller inventory.")
        return

    if len(sellers) < min_sellers_per_prod:
        print(f"Warning: Not enough sellers ({len(sellers)}) to meet the minimum requirement ({min_sellers_per_prod}). Adjusting target.")
        min_sellers_per_prod = len(sellers)

    if min_sellers_per_prod <= 0:
        print("Minimum sellers per product is 0 or less. Skipping seller inventory creation.")
        return

    print(f"Ensuring at least {min_sellers_per_prod} sellers per product in Inventory table...")

    existing_seller_map = {}
    for inv in session.query(Inventory.product_id, Inventory.seller_id).all():
        if inv.product_id not in existing_seller_map:
            existing_seller_map[inv.product_id] = set()
        existing_seller_map[inv.product_id].add(inv.seller_id)

    try:
        test_product = None
        if products:
            test_product = products[0]
        
        if test_product and test_product.product_id in product_warehouse_map:
            product_id = test_product.product_id
            assigned_warehouses = product_warehouse_map[product_id]
            
            if not assigned_warehouses:
                print(f"Warning: Test product {product_id} has no warehouses assigned.")
                if len(warehouses) > 0:
                    assigned_warehouses = [warehouses[0].warehouse_id]
            
            for seller in sellers:
                if seller.user_id == test_product.owner_id:
                    continue  # Skip the product owner
                
                warehouse_id = random.choice(assigned_warehouses) if assigned_warehouses else None
                # ...existing code continues...

    except Exception as e:
        print(f"Error creating test product inventory: {e}")
        session.rollback()

    product_count = 0
    added_count_total = 0
    for product in products:
        product_count += 1
        if product_count % 100 == 0:
            print(f"  Processing seller inventory for product {product_count}/{len(products)}...")

        current_sellers = existing_seller_map.get(product.product_id, set())
        sellers_needed = min_sellers_per_prod - len(current_sellers)
        
        assigned_warehouses = product_warehouse_map.get(product.product_id, [])
        if not assigned_warehouses:
            continue  # Skip products without warehouse assignments

        if sellers_needed > 0:
            potential_sellers = [s for s in sellers if s.user_id != product.owner_id and s.user_id not in current_sellers]

            if len(potential_sellers) < sellers_needed:
                 additional_potential = [s for s in sellers if s.user_id not in current_sellers]
                 combined_potential = list(dict.fromkeys(potential_sellers + additional_potential))
                 potential_sellers = combined_potential

            num_to_add = min(sellers_needed, len(potential_sellers))
            if num_to_add > 0:
                sellers_to_add = random.sample(potential_sellers, num_to_add)

                for seller in sellers_to_add:
                    quantity = random.randint(20, MAX_INITIAL_INVENTORY)
                    unit_price = round(float(product.price) * random.uniform(0.90, 1.25), 2)
                    unit_price = max(0.01, unit_price)
                    warehouse_id = random.choice(assigned_warehouses)

                    inventory_item = Inventory(
                        seller_id=seller.user_id,
                        product_id=product.product_id,
                        quantity=quantity,
                        unit_price=unit_price,
                        owner_id=product.owner_id,
                        warehouse_id=warehouse_id
                    )
                    inventory_items_to_add.append(inventory_item)
                    added_count_total += 1
                    if product.product_id not in existing_seller_map:
                         existing_seller_map[product.product_id] = set()
                    existing_seller_map[product.product_id].add(seller.user_id)

    if inventory_items_to_add:
        try:
            session.add_all(inventory_items_to_add)
            session.commit()
            print(f"Successfully added {added_count_total} new seller inventory listings.")
        except SQLAlchemyError as e:
            session.rollback()
            print(f"Error adding seller inventory listings: {e}")

def create_carts_and_orders(users, products, n_orders_per_user, max_items):
    Order = db_models['Order']
    OrderProduct = db_models['OrderProduct']
    Cart = db_models['Cart']

    orders_created_list = []
    buyers = [u for u in users if not u.is_seller]
    if not buyers or not products:
        print("Error: Buyers and products are required to create orders.")
        return []

    print(f"Creating up to {n_orders_per_user} orders for each of {len(buyers)} buyers...")
    total_order_count = 0
    buyer_count = 0

    existing_carts = {cart.user_id: cart for cart in session.query(Cart).filter(Cart.user_id.in_([b.user_id for b in buyers])).all()}

    for buyer in buyers:
        buyer_count += 1
        if buyer_count % 50 == 0:
             print(f"  Processing orders for buyer {buyer_count}/{len(buyers)}...")

        cart = existing_carts.get(buyer.user_id)
        if not cart:
            cart = Cart(user_id=buyer.user_id)
            session.add(cart)
            try:
                session.flush()
                existing_carts[buyer.user_id] = cart
            except SQLAlchemyError as e:
                 session.rollback()
                 print(f"Failed to create cart for user {buyer.user_id}: {e}")
                 continue

        orders_for_this_user = 0
        num_orders_to_create_for_user = random.randint(0, n_orders_per_user)

        for _ in range(num_orders_to_create_for_user):
            num_items_in_order = random.randint(1, max_items)
            order_total = 0
            items_for_order = []
            product_ids_in_order = set()

            available_listings = session.query(Inventory).filter(
                Inventory.quantity > 0,
                Inventory.seller_id != buyer.user_id,
                Inventory.warehouse_id != None
            ).all()

            if not available_listings: continue

            for _ in range(num_items_in_order):
                if not available_listings: break
                chosen_listing = random.choice(available_listings)

                if chosen_listing.product_id in product_ids_in_order: continue

                quantity = random.randint(1, min(4, chosen_listing.quantity))
                price = chosen_listing.unit_price
                order_total += price * quantity
                items_for_order.append({
                    'product_id': chosen_listing.product_id,
                    'quantity': quantity,
                    'price': price,
                    'seller_id': chosen_listing.seller_id,
                    'warehouse_id': chosen_listing.warehouse_id
                })
                product_ids_in_order.add(chosen_listing.product_id)
                available_listings.remove(chosen_listing)

            if not items_for_order: continue

            order_date = fake.date_time_between(start_date="-1y", end_date="now", tzinfo=None)

            order = Order(
                buyer_id=buyer.user_id,
                total_amount=round(order_total, 2),
                num_products=sum(item['quantity'] for item in items_for_order),
                order_status='Unfulfilled',
                order_date=order_date
            )
            session.add(order)
            try:
                session.flush()
            except SQLAlchemyError as e:
                session.rollback()
                print(f"Failed to create order for user {buyer.user_id} (flush): {e}")
                continue

            order_items_to_add = []
            for item_data in items_for_order:
                order_product = OrderProduct(
                    order_id=order.order_id,
                    product_id=item_data['product_id'],
                    quantity=item_data['quantity'],
                    price=item_data['price'],
                    seller_id=item_data['seller_id'],
                    status='Unfulfilled'
                )
                order_items_to_add.append(order_product)

            session.add_all(order_items_to_add)

            try:
                session.commit()
                orders_created_list.append(order)
                orders_for_this_user += 1
                total_order_count += 1
            except IntegrityError as e:
                 session.rollback()
                 print(f"Failed to add order items (IntegrityError) for order {order.order_id}: {e}")
            except SQLAlchemyError as e:
                session.rollback()
                print(f"Failed to commit order {order.order_id} for user {buyer.user_id}: {e}")

    print(f"Successfully created {total_order_count} orders.")
    return orders_created_list

def create_shipments(orders, warehouses, n_shipments_to_create):
    Shipment = db_models['Shipment']
    ShipmentItem = db_models['ShipmentItem']
    OrderProduct = db_models['OrderProduct']
    Order = db_models['Order']
    User = db_models['User']

    shipments_created_list = []

    if not orders:
        print("No orders available to create shipments for.")
        return []
    if not warehouses:
        print("Error: Warehouses are required to create shipments.")
        return []

    eligible_orders = session.query(Order).filter(
        Order.items.any(OrderProduct.status == 'Unfulfilled')
    ).filter(
        ~Order.shipments.any()
    ).all()

    num_to_sample = min(n_shipments_to_create, len(eligible_orders))
    if num_to_sample <= 0:
        print("No suitable orders found to create shipments.")
        return []

    orders_for_shipment = random.sample(eligible_orders, num_to_sample)

    print(f"Attempting to create shipments for {len(orders_for_shipment)} orders...")
    shipment_count = 0
    processed_orders = set()

    for order in orders_for_shipment:
        if order.order_id in processed_orders: continue

        order_items = session.query(OrderProduct).filter_by(order_id=order.order_id).all()
        if not order_items:
            continue
            
        sample_order_item = order_items[0]
        inventory_item = session.query(Inventory).filter_by(
            product_id=sample_order_item.product_id,
            seller_id=sample_order_item.seller_id
        ).first()
        
        if inventory_item and inventory_item.warehouse_id:
            warehouse_id = inventory_item.warehouse_id
            warehouse = session.query(Warehouse).get(warehouse_id)
        else:
            warehouse = random.choice(warehouses)
            
        buyer = session.get(User, order.buyer_id)
        if buyer and buyer.address:
             dest_x = (hash(buyer.address + "x_coord") % 90) + 5
             dest_y = (hash(buyer.address + "y_coord") % 90) + 5
             dest_x = max(0, min(100, dest_x))
             dest_y = max(0, min(100, dest_y))
        else:
             dest_x = random.randint(5, 95)
             dest_y = random.randint(5, 95)

        now = datetime.now()
        order_date_naive = order.order_date.replace(tzinfo=None) if order.order_date.tzinfo else order.order_date
        days_since_order = (now - order_date_naive).days
        status = 'packing'
        ups_tracking_id = None
        truck_id = None
        fulfillment_date = None

        if days_since_order > 30 and random.random() < 0.98: status = 'delivered'
        elif days_since_order > 7 and random.random() < 0.9: status = random.choice(['delivering', 'loaded'])
        elif days_since_order > 1 and random.random() < 0.8: status = random.choice(['packed', 'loading'])
        order_items_for_status_check = session.query(OrderProduct).filter_by(order_id=order.order_id).all()
        any_item_fulfilled = any(item.status == 'Fulfilled' for item in order_items_for_status_check)
        if any_item_fulfilled and status in ['packing', 'packed', 'loading']:
            status = 'loaded'

        if status != 'packing':
             ups_tracking_id = fake.ean(length=13)
        if status in ['loading', 'loaded', 'delivering', 'delivered']:
             truck_id = random.randint(1, 50)
        if status == 'delivered':
             min_fulfill_date = order_date_naive + timedelta(days=random.uniform(0.5, 3))
             if min_fulfill_date < now:
                 fulfillment_date = fake.date_time_between(start_date=min_fulfill_date, end_date=now, tzinfo=None)
             else:
                 fulfillment_date = now

        shipment = Shipment(
             order_id=order.order_id,
             warehouse_id=warehouse.warehouse_id,
             destination_x=dest_x,
             destination_y=dest_y,
             status=status,
             ups_tracking_id=ups_tracking_id,
             truck_id=truck_id,
             ups_account = buyer.email if buyer and random.random() < 0.1 else None
        )
        session.add(shipment)
        try:
            session.flush()
        except SQLAlchemyError as e:
             session.rollback()
             print(f"Failed to create shipment for order {order.order_id} (flush): {e}")
             continue

        order_items = order_items_for_status_check
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

        if status == 'delivered':
            try:
                 order.order_status = 'Fulfilled'
                 for item in order_items:
                     item.status = 'Fulfilled'
                     item.fulfillment_date = fulfillment_date

            except Exception as e:
                 print(f"Error updating order/item status for delivered shipment {shipment.shipment_id}: {e}")
                 session.rollback()
                 continue

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

def create_reviews(users, products, n_reviews_to_create):
    Review = db_models['Review']
    reviews_to_add = []
    buyers = [u for u in users if not u.is_seller]
    sellers = [u for u in users if u.is_seller]

    if not buyers:
        print("Error: Buyers are required to create reviews.")
        return []
    if not products and not sellers:
         print("Error: Products or Sellers are required to create reviews.")
         return []

    print(f"Attempting to create {n_reviews_to_create} reviews...")
    reviews_created = 0

    existing_product_reviews = {(r.user_id, r.product_id) for r in session.query(Review.user_id, Review.product_id).filter(Review.product_id != None).all()}
    existing_seller_reviews = {(r.user_id, r.seller_id) for r in session.query(Review.user_id, Review.seller_id).filter(Review.seller_id != None).all()}

    attempts = 0
    max_attempts = n_reviews_to_create * 4

    while reviews_created < n_reviews_to_create and attempts < max_attempts:
        attempts += 1
        reviewer = random.choice(buyers)
        review_target_type = random.choices(['product', 'seller'], weights=[0.8, 0.2])[0]

        if review_target_type == 'product' and products:
            target_product = random.choice(products)
            target_key = (reviewer.user_id, target_product.product_id)
            if target_key in existing_product_reviews: continue

            review = Review(
                user_id=reviewer.user_id,
                product_id=target_product.product_id,
                seller_id=None,
                rating=random.choices([1, 2, 3, 4, 5], weights=[0.05, 0.1, 0.2, 0.4, 0.25])[0],
                comment=fake.paragraph(nb_sentences=random.randint(1, 4)),
                review_date=fake.date_time_between(start_date="-6m", end_date="now", tzinfo=None)
            )
            reviews_to_add.append(review)
            existing_product_reviews.add(target_key)
            reviews_created += 1

        elif review_target_type == 'seller' and sellers:
            target_seller = random.choice(sellers)
            if reviewer.user_id == target_seller.user_id: continue

            target_key = (reviewer.user_id, target_seller.user_id)
            if target_key in existing_seller_reviews: continue

            review = Review(
                user_id=reviewer.user_id,
                product_id=None,
                seller_id=target_seller.user_id,
                rating=random.choices([1, 2, 3, 4, 5], weights=[0.08, 0.12, 0.2, 0.35, 0.25])[0],
                comment=fake.paragraph(nb_sentences=random.randint(1, 3)),
                review_date=fake.date_time_between(start_date="-6m", end_date="now", tzinfo=None)
            )
            reviews_to_add.append(review)
            existing_seller_reviews.add(target_key)
            reviews_created += 1

        if reviews_created > 0 and reviews_created % 500 == 0 and len(reviews_to_add) > 0:
             print(f"  Prepared {reviews_created}/{n_reviews_to_create} reviews...")

        if len(reviews_to_add) >= 500:
            try:
                 session.add_all(reviews_to_add)
                 session.commit()
                 print(f"  Committed batch of {len(reviews_to_add)} reviews.")
                 reviews_to_add = []
            except IntegrityError as e:
                 session.rollback()
                 print(f"Error creating reviews batch (IntegrityError likely duplicate): {e}")
                 reviews_to_add = []
            except SQLAlchemyError as e:
                session.rollback()
                print(f"Error creating reviews batch: {e}")
                reviews_to_add = []

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
        print(f"Warning: Reached max attempts ({max_attempts}) but only created {reviews_created}/{n_reviews_to_create} reviews. Might indicate high collision rate.")

    print(f"Successfully attempted to create reviews. Final count in DB will reflect committed entries.")
    final_count = session.query(func.count(Review.review_id)).scalar()
    print(f"Current total reviews in DB: {final_count}")
    return final_count

if __name__ == "__main__":
    print("Starting database seeding...")

    user_count = session.query(func.count(db_models['User'].user_id)).scalar()
    product_count = session.query(func.count(db_models['Product'].product_id)).scalar()
    order_count = session.query(func.count(db_models['Order'].order_id)).scalar()
    review_count = session.query(func.count(db_models['Review'].review_id)).scalar()
    inventory_count = session.query(func.count(db_models['Inventory'].inventory_id)).scalar()
    warehouse_inventory_count = session.query(func.count(db_models['WarehouseProduct'].id)).scalar()

    print(f"Current counts - Users: {user_count}, Products: {product_count}, Orders: {order_count}, Reviews: {review_count}, Seller Inventory: {inventory_count}, Warehouse Inventory: {warehouse_inventory_count}")

    skip_seeding = (
        user_count > NUM_USERS * 0.7 and
        product_count > (NUM_CATEGORIES * NUM_PRODUCTS_PER_CATEGORY * 0.7) and
        order_count > (NUM_USERS * NUM_ORDERS_PER_USER * 0.4) and
        review_count > (NUM_ORDERS_ESTIMATE * 0.5) and
        inventory_count > product_count * (MIN_SELLERS_PER_PRODUCT * 0.5)
    )

    if len(sys.argv) > 1 and sys.argv[1] == '--force':
         print("Force flag detected. Proceeding with seeding anyway...")
         skip_seeding = False
    elif skip_seeding:
        print(f"Database appears to have significant data already. Skipping full seeding run.")
        print("To force seeding on a populated DB, run with '--force' argument.")

    if not skip_seeding:
        print("Proceeding with full data seeding...")
        print("-" * 20)
        all_users = create_users(NUM_USERS, NUM_SELLERS)
        sellers = [u for u in all_users if u.is_seller]
        print(f"Total users in DB after creation/fetch: {session.query(func.count(db_models['User'].user_id)).scalar()}")
        print("-" * 20)

        all_categories = create_categories(NUM_CATEGORIES)
        print(f"Total categories in DB after creation/fetch: {session.query(func.count(db_models['ProductCategory'].category_id)).scalar()}")
        print("-" * 20)

        all_products = []
        if all_categories and sellers:
             all_products = create_products(all_categories, sellers, NUM_PRODUCTS_PER_CATEGORY)
             print(f"Total products in DB after creation: {session.query(func.count(db_models['Product'].product_id)).scalar()}")
        else:
             print("Skipping product creation due to missing categories or sellers.")
        print("-" * 20)

        all_warehouses = create_warehouses(NUM_WAREHOUSES)
        print(f"Total warehouses in DB after creation: {session.query(func.count(db_models['Warehouse'].warehouse_id)).scalar()}")
        print("-" * 20)

        product_warehouse_map = {}
        if all_products and all_warehouses:
            product_warehouse_map = create_warehouse_inventory(all_products, all_warehouses, MAX_INITIAL_INVENTORY)
            print(f"Total WAREHOUSE inventory records in DB: {session.query(func.count(db_models['WarehouseProduct'].id)).scalar()}")
        else:
             print("Skipping warehouse inventory creation due to missing products or warehouses.")
        print("-" * 20)

        if all_products and sellers and product_warehouse_map:
             create_seller_inventory(all_products, sellers, MIN_SELLERS_PER_PRODUCT, product_warehouse_map, all_warehouses)
             print(f"Total seller inventory listings in DB: {session.query(func.count(db_models['Inventory'].inventory_id)).scalar()}")
        else:
             print("Skipping seller inventory creation due to missing products, sellers, or warehouse assignments.")
        print("-" * 20)

        created_orders = []
        if all_users and all_products and session.query(func.count(db_models['Inventory'].inventory_id)).scalar() > 0:
            created_orders = create_carts_and_orders(all_users, all_products, NUM_ORDERS_PER_USER, MAX_ITEMS_PER_ORDER)
            print(f"Total orders in DB after creation: {session.query(func.count(db_models['Order'].order_id)).scalar()}")
        else:
            print("Skipping order creation due to missing users, products, or seller inventory.")
        print("-" * 20)

        all_db_orders = session.query(Order).all()
        if all_db_orders and all_warehouses:
             create_shipments(all_db_orders, all_warehouses, NUM_SHIPMENTS_TO_CREATE)
             print(f"Total shipments in DB after creation: {session.query(func.count(db_models['Shipment'].shipment_id)).scalar()}")
        else:
             print("Skipping shipment creation due to missing orders or warehouses.")
        print("-" * 20)

        if all_users and all_products:
            create_reviews(all_users, all_products, NUM_REVIEWS_TO_CREATE)
        else:
            print("Skipping review creation due to missing users or products.")
        print("-" * 20)

        print("Database seeding completed!")

    session.close()
    engine.dispose()
    print("Database session closed.")