# File: app/controllers/seller_controller.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from functools import wraps
from werkzeug.utils import secure_filename
import os
from datetime import datetime
from sqlalchemy import func

# Import necessary models and db object from your app.model
from app.model import db, User, Product, ProductCategory, Inventory, Order, OrderProduct

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
    """Seller dashboard overview"""
    seller_id = current_user.user_id

    # Get recent unfulfilled order items for this seller
    recent_order_items = db.session.query(OrderProduct).join(Order)\
        .filter(OrderProduct.seller_id == seller_id, OrderProduct.status == 'Unfulfilled')\
        .order_by(Order.order_date.desc())\
        .limit(5).all()

    # Get all inventory items for stats
    inventory_items = Inventory.query.filter_by(seller_id=seller_id).all()

    total_value = sum(item.quantity * float(item.unit_price) for item in inventory_items)
    low_stock_count = sum(1 for item in inventory_items if item.quantity < 5)
    inventory_count = len(inventory_items)

    # Count fulfilled/unfulfilled items associated with this seller
    fulfilled_items_count = db.session.query(func.sum(OrderProduct.quantity))\
        .filter(OrderProduct.seller_id == seller_id, OrderProduct.status == 'Fulfilled').scalar() or 0
    unfulfilled_items_count = db.session.query(func.sum(OrderProduct.quantity))\
        .filter(OrderProduct.seller_id == seller_id, OrderProduct.status == 'Unfulfilled').scalar() or 0

    return render_template(
        'seller/dashboard.html', # You will need to create this template
        recent_order_items=recent_order_items,
        inventory_items=inventory_items[:5], # Display first 5
        total_value=total_value,
        low_stock_count=low_stock_count,
        inventory_count=inventory_count,
        fulfilled_items_count=fulfilled_items_count,
        unfulfilled_items_count=unfulfilled_items_count
    )

# --- Inventory Management ---
@seller_bp.route('/inventory')
@seller_required
def inventory_list():
    """Seller inventory management view"""
    seller_id = current_user.user_id
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    category_id = request.args.get('category_id', type=int)
    per_page = 10

    # Base query for seller's inventory
    query = Inventory.query.filter(Inventory.seller_id == seller_id)\
                           .join(Product, Inventory.product_id == Product.product_id)

    # Apply search filter
    if search:
        query = query.filter(Product.product_name.ilike(f'%{search}%'))

    # Apply category filter
    if category_id:
        query = query.filter(Product.category_id == category_id)

    # Order and paginate
    pagination = query.order_by(Product.product_name.asc())\
                      .paginate(page=page, per_page=per_page, error_out=False)

    inventory_items = pagination.items
    categories = ProductCategory.query.order_by(ProductCategory.category_name).all()

    return render_template(
        'seller/inventory.html', # You will need to create this template
        inventory_items=inventory_items,
        categories=categories,
        current_category=category_id,
        search_query=search,
        pagination=pagination
    )

@seller_bp.route('/inventory/add', methods=['GET', 'POST'])
@seller_required
def add_inventory():
    """Add an existing product to seller's inventory"""
    seller_id = current_user.user_id

    if request.method == 'POST':
        product_id = request.form.get('product_id', type=int)
        quantity = request.form.get('quantity', type=int)
        unit_price = request.form.get('unit_price', type=float)

        if not product_id or quantity is None or unit_price is None:
            flash('Product, quantity, and price are required.', 'danger')
            return redirect(url_for('seller.add_inventory'))
        if quantity < 0:
            flash('Quantity cannot be negative.', 'danger')
            return redirect(url_for('seller.add_inventory'))
        if unit_price <= 0:
            flash('Price must be positive.', 'danger')
            return redirect(url_for('seller.add_inventory'))

        # Check if product exists
        product = Product.query.get(product_id)
        if not product:
            flash('Selected product does not exist.', 'danger')
            return redirect(url_for('seller.add_inventory'))

        # Check if already in inventory
        existing = Inventory.query.filter_by(seller_id=seller_id, product_id=product_id).first()
        if existing:
            flash('This product is already in your inventory. Use "Edit" to change quantity/price.', 'warning')
            return redirect(url_for('seller.inventory_list'))

        try:
            new_inventory = Inventory(
                seller_id=seller_id,
                product_id=product_id,
                quantity=quantity,
                unit_price=unit_price,
                owner_id=product.owner_id # Assuming product owner is relevant here
            )
            db.session.add(new_inventory)
            db.session.commit()
            flash('Product added to your inventory.', 'success')
            return redirect(url_for('seller.inventory_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding product to inventory: {str(e)}', 'danger')
            current_app.logger.error(f"Error adding inventory for seller {seller_id}: {e}")


    # GET request: Show available products NOT already in seller's inventory
    subquery = db.session.query(Inventory.product_id).filter(Inventory.seller_id == seller_id)
    available_products = Product.query.filter(Product.product_id.notin_(subquery)).order_by(Product.product_name).all()
    categories = ProductCategory.query.order_by(ProductCategory.category_name).all()

    return render_template(
        'seller/add_inventory.html', # You will need to create this template
        available_products=available_products,
        categories=categories # For potential filtering on the add page
    )


@seller_bp.route('/product/create', methods=['GET', 'POST'])
@seller_required
def create_product():
    """Create a new product and add it to inventory"""
    seller_id = current_user.user_id

    if request.method == 'POST':
        product_name = request.form.get('product_name')
        category_id = request.form.get('category_id', type=int)
        description = request.form.get('description')
        quantity = request.form.get('quantity', type=int)
        unit_price = request.form.get('unit_price', type=float)
        image_url = None # Placeholder for image handling

        # --- Basic Validation ---
        if not all([product_name, category_id, description, quantity is not None, unit_price is not None]):
            flash('Please fill in all required fields.', 'danger')
            return redirect(url_for('seller.create_product'))
        if quantity < 0:
            flash('Quantity cannot be negative.', 'danger')
            return redirect(url_for('seller.create_product'))
        if unit_price <= 0:
            flash('Price must be positive.', 'danger')
            return redirect(url_for('seller.create_product'))

        # --- Image Upload Handling (Optional but recommended) ---
        if 'product_image' in request.files:
            file = request.files['product_image']
            if file and file.filename:
                # Basic check for allowed extensions (customize as needed)
                allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
                if '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                    filename = secure_filename(file.filename)
                    # Create unique filename
                    unique_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{seller_id}_{filename}"
                    upload_folder = current_app.config.get('UPLOAD_FOLDER', os.path.join(current_app.instance_path, 'uploads'))
                    if not os.path.exists(upload_folder):
                         os.makedirs(upload_folder)
                    file_path = os.path.join(upload_folder, unique_filename)
                    try:
                        file.save(file_path)
                        # Store a relative URL accessible via static endpoint
                        image_url = f"uploads/{unique_filename}" # Adjust if your static setup differs
                        flash(f"Image '{filename}' uploaded.", 'info')
                    except Exception as e:
                        flash(f"Failed to save image: {str(e)}", 'danger')
                        current_app.logger.error(f"Image save failed: {e}")
                else:
                     flash('Invalid image file type.', 'warning')


        try:
            # Create Product first
            new_product = Product(
                product_name=product_name,
                category_id=category_id,
                description=description,
                price=unit_price, # Use seller's price as base product price? Or separate?
                owner_id=seller_id, # Product owner is the seller creating it
                image=image_url
            )
            db.session.add(new_product)
            db.session.flush() # Get the new product_id

            # Add to Inventory
            new_inventory = Inventory(
                seller_id=seller_id,
                product_id=new_product.product_id,
                quantity=quantity,
                unit_price=unit_price,
                owner_id=seller_id # Product owner is the seller
            )
            db.session.add(new_inventory)
            db.session.commit()
            flash('New product created and added to your inventory!', 'success')
            return redirect(url_for('seller.inventory_list'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error creating product or inventory: {str(e)}', 'danger')
            current_app.logger.error(f"Error in create_product for seller {seller_id}: {e}")

    # GET request
    categories = ProductCategory.query.order_by(ProductCategory.category_name).all()
    return render_template(
        'seller/create_product.html', # You will need to create this template
        categories=categories
    )

@seller_bp.route('/inventory/edit/<int:inventory_id>', methods=['GET', 'POST'])
@seller_required
def edit_inventory(inventory_id):
    """Edit quantity and price for an inventory item"""
    seller_id = current_user.user_id
    item = Inventory.query.get_or_404(inventory_id)

    # Ensure the seller owns this inventory item
    if item.seller_id != seller_id:
        flash('You do not have permission to edit this item.', 'danger')
        return redirect(url_for('seller.inventory_list'))

    if request.method == 'POST':
        quantity = request.form.get('quantity', type=int)
        unit_price = request.form.get('unit_price', type=float)

        if quantity is None or unit_price is None:
            flash('Quantity and price are required.', 'danger')
            return render_template('seller/edit_inventory.html', item=item)
        if quantity < 0:
            flash('Quantity cannot be negative.', 'danger')
            return render_template('seller/edit_inventory.html', item=item)
        if unit_price <= 0:
            flash('Price must be positive.', 'danger')
            return render_template('seller/edit_inventory.html', item=item)

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
    return render_template(
        'seller/edit_inventory.html', # You will need to create this template
        item=item
    )

@seller_bp.route('/inventory/delete/<int:inventory_id>', methods=['POST'])
@seller_required
def delete_inventory(inventory_id):
    """Remove an item from seller's inventory"""
    seller_id = current_user.user_id
    item = Inventory.query.get_or_404(inventory_id)

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
    order_item = OrderProduct.query.get_or_404(order_item_id)

    if order_item.seller_id != seller_id:
        flash('You cannot fulfill this item as you are not the seller.', 'danger')
        # Redirect back to the order details or orders list
        # Need order_id, find it via the relationship
        return redirect(request.referrer or url_for('seller.list_orders'))

    if order_item.status == 'Fulfilled':
        flash('This item has already been fulfilled.', 'info')
        return redirect(request.referrer or url_for('seller.list_orders'))

    try:
        order_item.status = 'Fulfilled'
        order_item.fulfillment_date = datetime.utcnow()

        # Optional: Check if all items in the parent order are fulfilled
        order = order_item.order
        all_fulfilled = all(item.status == 'Fulfilled' for item in order.items)
        if all_fulfilled:
            order.order_status = 'Fulfilled'

        db.session.commit()
        flash(f'Item "{order_item.product.product_name}" marked as fulfilled.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error fulfilling item: {str(e)}', 'danger')
        current_app.logger.error(f"Error fulfilling order item {order_item_id}: {e}")

    return redirect(request.referrer or url_for('seller.list_orders'))