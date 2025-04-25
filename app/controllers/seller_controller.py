from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify # Added jsonify
from flask_login import login_required, current_user
from functools import wraps
from werkzeug.utils import secure_filename
import os
from datetime import datetime, timedelta # Added timedelta
from sqlalchemy import func, cast, Date # Added cast, Date
from flask import request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from app.services.warehouse_service import WarehouseService
from app.model import Product, Warehouse # Import Warehouse if needed for validation/display
# Added Order, OrderProduct
from app.model import db, User, Product, ProductCategory, Inventory, Order, OrderProduct, WarehouseProduct
from sqlalchemy.orm import joinedload




# Helper function to check if user is logged in as a seller
def seller_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('amazon.login', next=request.url))
        if not current_user.is_seller:
            flash('You must be registered as a seller to access this page.', 'danger')
            return redirect(url_for('amazon.index'))
        return f(*args, **kwargs)
    return decorated_function

seller_bp = Blueprint('seller', __name__, url_prefix='/seller')

# --- Dashboard ---
@seller_bp.route('/dashboard')
@seller_required
def dashboard():
    """Seller dashboard overview with sales reports"""
    seller_id = current_user.user_id

    # --- Existing Inventory Stats ---
    inventory_items_query = Inventory.query.filter_by(seller_id=seller_id)
    inventory_items = inventory_items_query.all()
    total_value = sum(item.quantity * float(item.unit_price) for item in inventory_items)
    low_stock_count = sum(1 for item in inventory_items if item.quantity < 5)
    inventory_count = len(inventory_items)

    # --- Order Item Stats ---
    fulfilled_items_count = db.session.query(func.sum(OrderProduct.quantity))\
        .filter(OrderProduct.seller_id == seller_id, OrderProduct.status == 'Fulfilled').scalar() or 0
    unfulfilled_items_count = db.session.query(func.sum(OrderProduct.quantity))\
        .filter(OrderProduct.seller_id == seller_id, OrderProduct.status == 'Unfulfilled')\
        .join(Order)\
        .scalar() or 0 # Joined Order to filter by order date later if needed

    recent_order_items = db.session.query(OrderProduct).join(Order)\
        .filter(OrderProduct.seller_id == seller_id, OrderProduct.status == 'Unfulfilled')\
        .order_by(Order.order_date.desc())\
        .limit(5).all()

    # --- NEW: Sales Report Data ---

    # 1. Total Sales Value (Last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    total_sales_last_30d = db.session.query(func.sum(OrderProduct.price * OrderProduct.quantity))\
        .join(Order)\
        .filter(OrderProduct.seller_id == seller_id, OrderProduct.status == 'Fulfilled', Order.order_date >= thirty_days_ago)\
        .scalar() or 0.0

    # 2. Sales Over Time (Last 30 days for Chart)
    sales_over_time = db.session.query(
            cast(Order.order_date, Date).label('sale_date'),
            func.sum(OrderProduct.price * OrderProduct.quantity).label('daily_total')
        )\
        .join(OrderProduct, Order.order_id == OrderProduct.order_id)\
        .filter(OrderProduct.seller_id == seller_id, OrderProduct.status == 'Fulfilled', Order.order_date >= thirty_days_ago)\
        .group_by(cast(Order.order_date, Date))\
        .order_by(cast(Order.order_date, Date))\
        .all()

    # Format for Chart.js
    sales_chart_labels = [d.sale_date.strftime('%Y-%m-%d') for d in sales_over_time]
    sales_chart_data = [float(d.daily_total) for d in sales_over_time]

    # 3. Top 5 Best Selling Products (by Quantity Fulfilled)
    top_products_query = db.session.query(
            Product.product_name,
            func.sum(OrderProduct.quantity).label('total_quantity')
        )\
        .join(OrderProduct, Product.product_id == OrderProduct.product_id)\
        .filter(OrderProduct.seller_id == seller_id, OrderProduct.status == 'Fulfilled')\
        .group_by(Product.product_name)\
        .order_by(func.sum(OrderProduct.quantity).desc())\
        .limit(5)\
        .all()

    # Format for Chart.js
    top_products_labels = [p.product_name for p in top_products_query]
    top_products_data = [int(p.total_quantity) for p in top_products_query]


    return render_template(
        'seller/dashboard.html', # Ensure this template exists
        recent_order_items=recent_order_items,
        inventory_items=inventory_items[:5], # Display first 5 inventory items
        total_value=total_value,
        low_stock_count=low_stock_count,
        inventory_count=inventory_count,
        fulfilled_items_count=fulfilled_items_count,
        unfulfilled_items_count=unfulfilled_items_count,
        # --- NEW DATA FOR REPORTS ---
        total_sales_last_30d=total_sales_last_30d,
        sales_chart_labels=sales_chart_labels,
        sales_chart_data=sales_chart_data,
        top_products_labels=top_products_labels,
        top_products_data=top_products_data
    )


@seller_bp.route('/inventory')
@seller_required
def inventory_list():
    """Seller inventory management view with optimized warehouse stock fetching."""
    seller_id = current_user.user_id
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    category_id = request.args.get('category_id', type=int)
    per_page = 10 # Or your preferred number

    # Base query for seller's inventory items (Inventory records)
    # Use joinedload to pre-fetch related Product and Category data
    query = Inventory.query.options(
        joinedload(Inventory.product).joinedload(Product.category)
    ).filter(Inventory.seller_id == seller_id)\
     .join(Product, Inventory.product_id == Product.product_id) # Explicit join might still be needed for filtering

    # Apply search filter on Product name
    if search:
        query = query.filter(Product.product_name.ilike(f'%{search}%'))

    # Apply category filter on Product category_id
    if category_id:
        query = query.filter(Product.category_id == category_id)

    # Order and paginate the Inventory listings
    pagination = query.order_by(Product.product_name.asc())\
                      .paginate(page=page, per_page=per_page, error_out=False)

    inventory_items = pagination.items # These are Inventory objects

    # --- Efficiently fetch warehouse stock for the products on the current page ---
    product_ids_on_page = [item.product_id for item in inventory_items]
    warehouse_stock_data = {} # {product_id: {warehouse_id: quantity}}

    if product_ids_on_page:
        # Query WarehouseProduct table for relevant products
        stock_entries = WarehouseProduct.query.filter(
            WarehouseProduct.product_id.in_(product_ids_on_page)
        ).all()

        # Structure the data for easy lookup in the template
        for entry in stock_entries:
            if entry.product_id not in warehouse_stock_data:
                warehouse_stock_data[entry.product_id] = {}
            warehouse_stock_data[entry.product_id][entry.warehouse_id] = entry.quantity

    # Add the fetched stock data directly to each inventory item for template access
    for item in inventory_items:
        item.warehouse_stock_map = warehouse_stock_data.get(item.product_id, {}) # Attach the map

    # --- Fetch other necessary data for template ---
    categories = ProductCategory.query.order_by(ProductCategory.category_name).all()
    # Fetch active warehouses for the modals in the inventory list
    warehouses = Warehouse.query.filter_by(active=True).order_by(Warehouse.warehouse_id).all()

    return render_template(
        'seller/inventory.html',
        inventory_items=inventory_items, # Now items have .warehouse_stock_map
        categories=categories,
        current_category=category_id,
        search_query=search,
        pagination=pagination,
        warehouses=warehouses # Pass warehouses for modals
    )


@seller_bp.route('/inventory/add', methods=['GET', 'POST'])
@seller_required
def add_inventory():
    """Add an existing product to seller's inventory AND add initial stock to a specified warehouse"""
    seller_id = current_user.user_id
    # Instantiate WarehouseService here or ensure it's accessible
    warehouse_service = WarehouseService(current_app.config.get('WORLD_SIMULATOR_SERVICE'))
    

    if request.method == 'POST':
        product_id = request.form.get('product_id', type=int)
        warehouse_id = request.form.get('warehouse_id', type=int) # Get selected warehouse ID
        quantity = request.form.get('quantity', type=int)
        unit_price = request.form.get('unit_price', type=float)

        # --- Validation ---
        if not all([product_id, warehouse_id, quantity is not None, unit_price is not None]):
            flash('Product, Warehouse, quantity, and price are required.', 'danger')
            # Fetch data again for GET part of template rendering
            subquery = db.session.query(Inventory.product_id).filter(Inventory.seller_id == seller_id)
            available_products = Product.query.filter(Product.product_id.notin_(subquery)).order_by(Product.product_name).all()
            categories = ProductCategory.query.order_by(ProductCategory.category_name).all()
            warehouses = Warehouse.query.filter_by(active=True).order_by(Warehouse.warehouse_id).all()
            return render_template('seller/add_inventory.html', available_products=available_products, categories=categories, warehouses=warehouses)

        if quantity <= 0: # Changed from < 0 to <= 0 as 0 quantity doesn't make sense here
            flash('Quantity must be positive.', 'danger')
            return redirect(url_for('seller.add_inventory')) # Redirect back to GET
        if unit_price <= 0:
            flash('Price must be positive.', 'danger')
            return redirect(url_for('seller.add_inventory')) # Redirect back to GET

        # Check if product exists
        product = Product.query.get(product_id)
        if not product:
            flash('Selected product does not exist.', 'danger')
            return redirect(url_for('seller.add_inventory'))

        # Check if warehouse exists and is active
        warehouse = Warehouse.query.filter_by(warehouse_id=warehouse_id, active=True).first()
        if not warehouse:
            flash('Selected warehouse is invalid or inactive.', 'danger')
            return redirect(url_for('seller.add_inventory'))

        # Check if already in seller's Inventory listing
        existing = Inventory.query.filter_by(seller_id=seller_id, product_id=product_id).first()
        if existing:
            flash('This product is already in your inventory listing. Use "Manage Stock" on the inventory page to add stock to warehouses.', 'warning')
            return redirect(url_for('seller.inventory_list'))

        try:
            # Step 1: Create the seller's Inventory LISTING
            new_inventory_listing = Inventory(
                seller_id=seller_id,
                product_id=product_id,
                quantity=quantity, # This represents the quantity the seller *lists*
                unit_price=unit_price,
                owner_id=product.owner_id
            )
            db.session.add(new_inventory_listing)
            db.session.commit() # Commit the listing first

            # Step 2: Add the PHYSICAL stock to the selected warehouse
            stock_success, stock_message = warehouse_service.add_product_to_warehouse(
                warehouse_id=warehouse_id,
                product_id=product_id,
                quantity=quantity # Add the specified initial quantity
            )

            if stock_success:
                flash(f'Product listed in your inventory and {quantity} units added to Warehouse #{warehouse_id}.', 'success')
            else:
                # Listing was created, but adding stock failed - inform the user
                flash(f'Product listed in your inventory, but failed to add stock to Warehouse #{warehouse_id}: {stock_message}. Please add stock manually.', 'warning')

            return redirect(url_for('seller.inventory_list'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error adding product: {str(e)}', 'danger')
            current_app.logger.error(f"Error adding inventory for seller {seller_id}: {e}")
            return redirect(url_for('seller.add_inventory')) # Redirect back to GET on generic error


    # --- GET request ---
    # Fetch available products NOT already in seller's Inventory listing
    subquery = db.session.query(Inventory.product_id).filter(Inventory.seller_id == seller_id)
    available_products = Product.query.filter(Product.product_id.notin_(subquery)).order_by(Product.product_name).all()
    categories = ProductCategory.query.order_by(ProductCategory.category_name).all()
    # Fetch active warehouses for the dropdown
    warehouses = Warehouse.query.filter_by(active=True).order_by(Warehouse.warehouse_id).all()

    return render_template(
        'seller/add_inventory.html',
        available_products=available_products,
        categories=categories,
        warehouses=warehouses # Pass warehouses to the template
    )


@seller_bp.route('/product/create', methods=['GET', 'POST'])
@seller_required
def create_product():
    """Create a new product, add it to seller's inventory listing, AND add initial stock to a specified warehouse"""
    seller_id = current_user.user_id
    # Instantiate WarehouseService
    warehouse_service = WarehouseService()

    if request.method == 'POST':
        product_name = request.form.get('product_name')
        category_id = request.form.get('category_id', type=int)
        description = request.form.get('description')
        warehouse_id = request.form.get('warehouse_id', type=int) # Get selected warehouse ID
        quantity = request.form.get('quantity', type=int)
        unit_price = request.form.get('unit_price', type=float)
        image_url = None # Placeholder for image handling

        # --- Basic Validation ---
        if not all([product_name, category_id, description, warehouse_id, quantity is not None, unit_price is not None]):
            flash('Please fill in all required fields, including the warehouse.', 'danger')
             # Fetch categories and warehouses again for re-rendering the form
            categories = ProductCategory.query.order_by(ProductCategory.category_name).all()
            warehouses = Warehouse.query.filter_by(active=True).order_by(Warehouse.warehouse_id).all()
            return render_template('seller/create_product.html', categories=categories, warehouses=warehouses)

        if quantity <= 0: # Changed from < 0
            flash('Quantity must be positive.', 'danger')
            return redirect(url_for('seller.create_product'))
        if unit_price <= 0:
            flash('Price must be positive.', 'danger')
            return redirect(url_for('seller.create_product'))

        # Validate warehouse
        warehouse = Warehouse.query.filter_by(warehouse_id=warehouse_id, active=True).first()
        if not warehouse:
            flash('Selected warehouse is invalid or inactive.', 'danger')
            return redirect(url_for('seller.create_product'))

        # --- Image Upload Handling (Optional but recommended) ---
        if 'product_image' in request.files:
            file = request.files['product_image']
            if file and file.filename:
                allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
                if '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                    filename = secure_filename(file.filename)
                    unique_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{seller_id}_{filename}"
                    upload_folder = current_app.config.get('UPLOAD_FOLDER', os.path.join(current_app.instance_path, 'uploads'))
                    if not os.path.exists(upload_folder):
                         os.makedirs(upload_folder)
                    file_path = os.path.join(upload_folder, unique_filename)
                    try:
                        file.save(file_path)
                        # Adjust this URL based on how you serve static files/uploads
                        image_url = url_for('static', filename=f"uploads/{unique_filename}", _external=False) # Use relative URL if possible
                        flash(f"Image '{filename}' uploaded.", 'info')
                    except Exception as e:
                        flash(f"Failed to save image: {str(e)}", 'danger')
                        current_app.logger.error(f"Image save failed: {e}")
                else:
                     flash('Invalid image file type.', 'warning')

        try:
            # Step 1: Create Product first
            new_product = Product(
                product_name=product_name,
                category_id=category_id,
                description=description,
                price=unit_price, # Base product price
                owner_id=seller_id,
                image=image_url
            )
            db.session.add(new_product)
            db.session.flush() # Get the new product_id

            # Step 2: Add to Seller's Inventory LISTING
            new_inventory_listing = Inventory(
                seller_id=seller_id,
                product_id=new_product.product_id,
                quantity=quantity, # Seller's listed quantity
                unit_price=unit_price,
                 warehouse_id=warehouse_id,
                owner_id=seller_id # Product owner is the seller
            )
            db.session.add(new_inventory_listing)
            db.session.commit() # Commit product and inventory listing

            # Step 3: First buy/register the product in the World Simulator
            world_simulator = current_app.config.get('WORLD_SIMULATOR_SERVICE')
            if world_simulator and world_simulator.connected:
                buy_success, buy_message = world_simulator.buy_product(
                    warehouse_id=warehouse_id,
                    product_id=new_product.product_id,
                    description=product_name,  # Use product name as description
                    quantity=quantity
                )
                
                if buy_success:
                    # Only add to warehouse inventory if successfully purchased in world
                    stock_success, stock_message = warehouse_service.add_product_to_warehouse(
                        warehouse_id=warehouse_id,
                        product_id=new_product.product_id,
                        quantity=quantity
                    )
                    
                    if stock_success:
                        flash(f'New product created, listed, and {quantity} units added to Warehouse #{warehouse_id}!', 'success')
                    else:
                        flash(f'Product registered in World but failed to add to local inventory: {stock_message}', 'warning')
                else:
                    flash(f'Failed to register product with World Simulator: {buy_message}', 'warning')
            else:
                # Fallback if not connected to world simulator
                stock_success, stock_message = warehouse_service.add_product_to_warehouse(
                    warehouse_id=warehouse_id,
                    product_id=new_product.product_id,
                    quantity=quantity
                )
                
                if stock_success:
                    flash(f'New product created and {quantity} units added to Warehouse #{warehouse_id}, but not connected to World Simulator.', 'warning')
                else:
                    flash(f'Product created but failed to add stock to warehouse: {stock_message}', 'warning')

            return redirect(url_for('seller.inventory_list'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error creating product or adding stock: {str(e)}', 'danger')
            current_app.logger.error(f"Error in create_product for seller {seller_id}: {e}")
            # Redirect back to GET on generic error
            return redirect(url_for('seller.create_product'))

    # --- GET request ---
    categories = ProductCategory.query.order_by(ProductCategory.category_name).all()
    # Fetch active warehouses for the dropdown
    warehouses = Warehouse.query.filter_by(active=True).order_by(Warehouse.warehouse_id).all()
    return render_template(
        'seller/create_product.html',
        categories=categories,
        warehouses=warehouses # Pass warehouses to the template
    )

@seller_bp.route('/inventory/edit/<int:inventory_id>', methods=['GET', 'POST'])
@seller_required
def edit_inventory(inventory_id):
    """Edit quantity and price for an inventory item"""
    seller_id = current_user.user_id
    # Use db.get_or_404 for simpler fetching by primary key
    item = db.session.get_or_404(Inventory, inventory_id)

    # Ensure the seller owns this inventory item
    if item.seller_id != seller_id:
        flash('You do not have permission to edit this item.', 'danger')
        return redirect(url_for('seller.inventory_list'))

    if request.method == 'POST':
        quantity = request.form.get('quantity', type=int)
        unit_price = request.form.get('unit_price', type=float)

        if quantity is None or unit_price is None:
            flash('Quantity and price are required.', 'danger')
            return render_template('seller/edit_inventory.html', item=item) # Pass item back
        if quantity < 0:
            flash('Quantity cannot be negative.', 'danger')
            return render_template('seller/edit_inventory.html', item=item) # Pass item back
        if unit_price <= 0:
            flash('Price must be positive.', 'danger')
            return render_template('seller/edit_inventory.html', item=item) # Pass item back

        try:
            item.quantity = quantity
            item.unit_price = unit_price
            item.updated_at = datetime.utcnow()
            db.session.commit()
            flash('Inventory item updated successfully.', 'success')
            return redirect(url_for('seller.inventory_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating inventory: {str(e)}', 'danger')
            current_app.logger.error(f"Error updating inventory {inventory_id}: {e}")

    # GET request
    # Fetch product details for display
    product = db.session.get(Product, item.product_id)
    return render_template(
        'seller/edit_inventory.html', # You will need to create this template
        item=item,
        product=product # Pass product details
    )

@seller_bp.route('/inventory/delete/<int:inventory_id>', methods=['POST'])
@seller_required
def delete_inventory(inventory_id):
    """Remove an item from seller's inventory"""
    seller_id = current_user.user_id
    item = db.session.get_or_404(Inventory, inventory_id)

    if item.seller_id != seller_id:
        flash('You do not have permission to delete this item.', 'danger')
        return redirect(url_for('seller.inventory_list'))

    try:
        db.session.delete(item)
        db.session.commit()
        flash('Inventory item removed.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error removing inventory item: {str(e)}', 'danger')
        current_app.logger.error(f"Error deleting inventory {inventory_id}: {e}")

    return redirect(url_for('seller.inventory_list'))


# --- Order Fulfillment ---
# ... (keep existing order routes: list_orders, fulfill_item) ...
@seller_bp.route('/orders')
@seller_required
def list_orders():
    """View orders containing items sold by this seller"""
    seller_id = current_user.user_id
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status', 'Unfulfilled') # Default to Unfulfilled
    per_page = 10

    # Query OrderProduct items linked to this seller
    query = OrderProduct.query.filter(OrderProduct.seller_id == seller_id)\
                              .join(Order).join(Product) # Join for order date and product name

    if status_filter:
         query = query.filter(OrderProduct.status == status_filter)

    pagination = query.order_by(Order.order_date.desc())\
                      .paginate(page=page, per_page=per_page, error_out=False)

    order_items = pagination.items

    return render_template(
        'seller/orders.html', # You will need to create this template
        order_items=order_items,
        current_status=status_filter,
        pagination=pagination
    )

@seller_bp.route('/orders/fulfill/<int:order_item_id>', methods=['POST'])
@seller_required
def fulfill_item(order_item_id):
    """Mark an order item sold by this seller as fulfilled"""
    seller_id = current_user.user_id
    # Use db.get_or_404 for simpler fetching by primary key
    order_item = db.session.get_or_404(OrderProduct, order_item_id)

    if order_item.seller_id != seller_id:
        flash('You cannot fulfill this item as you are not the seller.', 'danger')
        return redirect(request.referrer or url_for('seller.list_orders'))

    if order_item.status == 'Fulfilled':
        flash('This item has already been fulfilled.', 'info')
        return redirect(request.referrer or url_for('seller.list_orders'))

    try:
        order_item.status = 'Fulfilled'
        order_item.fulfillment_date = datetime.utcnow()


        order = order_item.order # Access via relationship
        all_items = order.items # Access via relationship
        all_fulfilled = all(item.status == 'Fulfilled' for item in all_items)
        if all_fulfilled:
            order.order_status = 'Fulfilled'

        db.session.commit()
        flash(f'Item "{order_item.product.product_name}" marked as fulfilled.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error fulfilling item: {str(e)}', 'danger')
        current_app.logger.error(f"Error fulfilling order item {order_item_id}: {e}")

    return redirect(request.referrer or url_for('seller.list_orders'))

from app.services.warehouse_service import WarehouseService
from app.model import db, User, Product, ProductCategory, Inventory, Order, OrderProduct, Warehouse


@seller_bp.route('/inventory/add-to-warehouse', methods=['POST'])
@seller_required
def add_stock_to_warehouse():
    """Handles adding stock to a specific warehouse for a product."""
    try:
        product_id = request.form.get('product_id', type=int)
        warehouse_id = request.form.get('warehouse_id', type=int)
        quantity_to_add = request.form.get('quantity_to_add', type=int)
        # Get the referring page to redirect back later
        referrer = request.form.get('referrer', url_for('seller.inventory_list'))

        # --- Validation ---
        if not product_id or not warehouse_id or quantity_to_add is None:
            flash('Missing product ID, warehouse ID, or quantity.', 'danger')
            return redirect(referrer)

        if quantity_to_add <= 0:
            flash('Quantity to add must be positive.', 'danger')
            return redirect(referrer)

        # Optional: Add permission check - does the seller actually list this product?
        # inventory_item = Inventory.query.filter_by(seller_id=current_user.user_id, product_id=product_id).first()
        # if not inventory_item:
        #     flash('You do not have this product listed in your inventory.', 'danger')
        #     return redirect(referrer)

        # --- Call Service ---
        # Assuming WarehouseService can be instantiated directly or fetched from app context
        warehouse_service = WarehouseService(current_app.config.get('WORLD_SIMULATOR_SERVICE'))
        # Use the existing add_product_to_warehouse function
        success, message = warehouse_service.add_product_to_warehouse(
            warehouse_id=warehouse_id,
            product_id=product_id,
            quantity=quantity_to_add # Pass the quantity *to add*
        )

        if success:
            product = Product.query.get(product_id) # Fetch product for message
            product_name = product.product_name if product else f"ID {product_id}"
            flash(f'Successfully added {quantity_to_add} units of {product_name} to Warehouse ID {warehouse_id}.', 'success')
        else:
            flash(f'Failed to add stock: {message}', 'danger')

        return redirect(referrer) # Redirect back to the inventory page or where the request came from

    except Exception as e:
        # Log the error properly in a real application
        current_app.logger.error(f"Error adding stock to warehouse: {e}", exc_info=True)
        flash(f'An unexpected error occurred: {str(e)}', 'danger')
        # Redirect back to a safe page, maybe the main inventory list
        return redirect(url_for('seller.inventory_list'))
    

@seller_bp.route('/inventory/replenish', methods=['POST'])
@seller_required
def replenish_inventory():
    """Handles request to replenish stock for a product."""
    product_id = request.form.get('product_id', type=int)
    quantity = request.form.get('quantity', type=int)
    warehouse_id = request.form.get('warehouse_id', type=int)
    referrer = request.form.get('referrer', url_for('seller.inventory_list'))

    # Validation
    if not product_id or not quantity or quantity <= 0 or not warehouse_id:
        flash('Invalid parameters specified.', 'danger')
        return redirect(referrer)

    # Call the service
    warehouse_service = WarehouseService(current_app.config.get('WORLD_SIMULATOR_SERVICE'))
    success, message = warehouse_service.replenish_product(
        warehouse_id=warehouse_id,
        product_id=product_id,
        quantity=quantity
    )

    if success:
        flash(f'Replenishment request for {quantity} of Product ID {product_id} sent to Warehouse ID {warehouse_id}. Status: {message}', 'success')
    else:
        flash(f'Failed to send replenishment request: {message}', 'danger')

    return redirect(referrer)