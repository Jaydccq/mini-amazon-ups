import os
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, flash, redirect, url_for, current_app
from flask_login import login_required, current_user, login_user, logout_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
# Assuming WTForms are defined in app.forms
# from app.forms import LoginForm, RegistrationForm # <-- Import your form classes here
from flask_wtf import FlaskForm # Example import for WTForms base class
from wtforms import StringField, PasswordField, BooleanField, SubmitField, IntegerField # Example field imports
from wtforms.validators import DataRequired, Email, EqualTo, ValidationError # Example validator imports

from app.model import db, Product, ProductCategory, Order, OrderProduct, User, Cart, CartProduct, Shipment, Warehouse
from app.services.warehouse_service import WarehouseService
from app.services.shipment_service import ShipmentService
# Import WorldSimulatorService to check connection status if needed
from app.services.world_simulator_service import WorldSimulatorService 

# Create blueprints
amazon_bp = Blueprint('amazon', __name__)
api_bp = Blueprint('api', __name__, url_prefix='/api')
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# Initialize services
warehouse_service = WarehouseService()
shipment_service = ShipmentService()
# Instantiate world_simulator if needed globally or within functions
# world_simulator = WorldSimulatorService() # Example instantiation


# --- Placeholder Form Definitions (Move to app/forms.py) ---
# Example: Replace these with your actual form definitions
class PlaceholderLoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')
    submit = SubmitField('Login')

class PlaceholderRegistrationForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    first_name = StringField('First Name', validators=[DataRequired()])
    last_name = StringField('Last Name', validators=[DataRequired()])
    # address = StringField('Address') # Optional field
    password = PasswordField('Password', validators=[DataRequired()])
    password2 = PasswordField(
        'Repeat Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user is not None:
            raise ValidationError('Please use a different email address.')
# --- End Placeholder Form Definitions ---


# Authentication routes
@amazon_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('amazon.index'))
        
    # *** MODIFIED: Use WTForms ***
    form = PlaceholderLoginForm() # Replace with your actual LoginForm
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('Invalid email or password', 'error')
            return redirect(url_for('amazon.login'))
            
        login_user(user, remember=form.remember_me.data)
        
        # Create cart if user doesn't have one (Consider moving this to user creation or first access)
        # It might be better to lazy-load the cart when first needed.
        # existing_cart = Cart.query.filter_by(user_id=user.user_id).first()
        # if not existing_cart:
        #     cart = Cart(user_id=user.user_id)
        #     db.session.add(cart)
        #     db.session.commit()
            
        next_page = request.args.get('next')
        if not next_page or not next_page.startswith('/'):
             next_page = url_for('amazon.index')
        flash('Login successful.', 'success')
        return redirect(next_page)
        
    # Pass form to template for GET requests or if validation fails
    return render_template('login.html', form=form) # Pass form object

@amazon_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('amazon.index'))
        
    # *** MODIFIED: Use WTForms ***
    form = PlaceholderRegistrationForm() # Replace with your actual RegistrationForm
    if form.validate_on_submit():
        new_user = User(
            email=form.email.data,
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            # address=form.address.data # If address field is included
        )
        new_user.set_password(form.password.data)
        db.session.add(new_user)
        # Commit here to get user_id for the cart
        try:
            db.session.commit() 
            # Create cart for the new user
            cart = Cart(user_id=new_user.user_id)
            db.session.add(cart)
            db.session.commit()
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('amazon.login'))
        except Exception as e:
             db.session.rollback()
             flash(f'Registration failed: {e}', 'error')

    # Pass form to template for GET requests or if validation fails
    return render_template('register.html', form=form) # Pass form object

@amazon_bp.route('/logout')
@login_required
def logout():
    """User logout"""
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('amazon.index'))

# Home page
@amazon_bp.route('/')
def index(): 
    try:
        # Get featured products
        products = Product.query.order_by(Product.created_at.desc()).limit(6).all()
        
        # Get product categories
        categories = ProductCategory.query.all()
    except Exception as e:
         flash(f'Error loading homepage data: {e}', 'error')
         products = []
         categories = []

    return render_template('index.html', 
                          products=products,
                          categories=categories)

# Product routes
@amazon_bp.route('/products')
def product_list():
    """List all products"""
    try:
        search_query = request.args.get('search', '')
        category_id = request.args.get('category_id', type=int)
        # Default sort: name ascending
        sort_by = request.args.get('sort_by', 'name') 
        sort_dir = request.args.get('sort_dir', 'asc')
        page = request.args.get('page', 1, type=int)
        
        per_page = 12
        products_query = Product.query
        
        if search_query:
            products_query = products_query.filter(
                db.or_( # Use OR for multiple search fields
                    Product.product_name.ilike(f'%{search_query}%'), 
                    Product.description.ilike(f'%{search_query}%')
                )
            )
        
        if category_id:
            products_query = products_query.filter(Product.category_id == category_id)
        
        # Apply sorting
        order_by_column = Product.product_name # Default
        if sort_by == 'price':
            order_by_column = Product.price
        elif sort_by == 'newest':
             order_by_column = Product.created_at
             sort_dir = 'desc' # Newest should always be descending

        if sort_dir == 'desc':
             products_query = products_query.order_by(order_by_column.desc())
        else:
             # Default to ascending for name/price or if sort_dir is invalid
             products_query = products_query.order_by(order_by_column.asc())

        # Get categories for sidebar
        categories = ProductCategory.query.all()
        
        # Paginate results
        pagination = products_query.paginate(page=page, per_page=per_page, error_out=False)
        
        products = pagination.items

    except Exception as e:
        flash(f'Error loading products: {e}', 'error')
        products = []
        pagination = None
        categories = []
    
    return render_template('products/list.html', 
                          products=products,          # Pass the list of items for the current page
                          pagination=pagination,      # Pass the whole pagination object
                          categories=categories,
                          search_query=search_query,
                          category_id=category_id,
                          sort_by=sort_by,
                          sort_dir=sort_dir)

@amazon_bp.route('/products/<int:product_id>')
def product_detail(product_id):
    try:
        # Query product and eagerly load category and owner for efficiency
        product = Product.query.options(
            db.joinedload(Product.category), 
            db.joinedload(Product.owner) 
        ).get_or_404(product_id)
        
        # Get warehouse inventory for this product using the service
        # The service currently returns a list of dicts, which is fine for the template
        inventory = warehouse_service.get_product_inventory(product_id) 
        
        # Get related products (same category, different product)
        related_products = Product.query.filter(
            Product.category_id == product.category_id,
            Product.product_id != product.product_id
        ).limit(4).all()

        # Placeholder for additional data needed by the template (if not loaded via relationships)
        # E.g., review stats, specific warehouse details if needed beyond what service provides
        # product.avg_rating = ... 
        # product.review_count = ...
        # product.rating_distribution = ...
        # product.warehouses = ... (might need another query or modification to inventory service)
        
        # Add owner_name if not loaded via relationship automatically
        if product.owner:
             product.owner_name = f"{product.owner.first_name} {product.owner.last_name}"
        else:
             product.owner_name = "Unknown Seller"

        # Add category_name if not loaded via relationship automatically
        if product.category:
            product.category_name = product.category.category_name
        else:
            product.category_name = "Uncategorized"

    except Exception as e:
        flash(f"Error loading product details: {e}", "error")
        return redirect(url_for('amazon.product_list'))

    return render_template('product_detail.html', # Changed template name based on previous requests
                          product=product,
                          inventory=inventory, # Pass inventory list from service
                          related_products=related_products)

# --- REMOVED Cart Routes (Assuming they are handled by cart_controller.py) ---
# @amazon_bp.route('/cart')
# @amazon_bp.route('/cart/add', methods=['POST'])
# @amazon_bp.route('/cart/update', methods=['POST'])
# @amazon_bp.route('/cart/remove', methods=['POST'])
# @amazon_bp.route('/checkout', methods=['GET', 'POST'])
# --- End REMOVED Cart Routes ---


# Order routes
@amazon_bp.route('/orders')
@login_required
def order_list():
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status') # Renamed variable
    
    try:
        # Get orders with filters and pagination
        per_page = 10
        orders_query = Order.query.filter_by(buyer_id=current_user.user_id)
        
        if status_filter: # Check if filter is present
            orders_query = orders_query.filter(Order.order_status == status_filter)
        
        orders_query = orders_query.order_by(Order.order_date.desc())
        
        # Eager load items and their products/sellers, and shipments for efficiency
        orders_query = orders_query.options(
            db.subqueryload(Order.items).joinedload(OrderProduct.product),
            db.subqueryload(Order.items).joinedload(OrderProduct.seller),
            db.subqueryload(Order.shipments)
        )

        # Paginate results
        pagination = orders_query.paginate(page=page, per_page=per_page, error_out=False)
        
        orders = pagination.items

    except Exception as e:
         flash(f"Error loading orders: {e}", "error")
         orders = []
         pagination = None

    return render_template('orders/list.html', 
                          orders=orders,        # List of orders for the current page
                          pagination=pagination,# Pagination object
                          status=status_filter) # Pass filter status back

@amazon_bp.route('/orders/<int:order_id>')
@login_required
def order_detail(order_id):
    try:
        # Eager load related data
        order = Order.query.options(
            db.joinedload(Order.user), # Load buyer info
            db.subqueryload(Order.items).joinedload(OrderProduct.product), # Load items and their products
            db.subqueryload(Order.items).joinedload(OrderProduct.seller),  # Load sellers for items
            db.subqueryload(Order.shipments) # Load shipments
        ).filter(Order.order_id == order_id).first_or_404()
        
        # Check if user owns this order
        if order.buyer_id != current_user.user_id:
            flash('You do not have permission to view this order', 'error')
            return redirect(url_for('amazon.order_list'))
        
        # Data is loaded via relationships, no need for separate queries for items/shipments
        items = order.items
        shipments = order.shipments

    except Exception as e:
        flash(f"Error loading order details: {e}", "error")
        return redirect(url_for('amazon.order_list'))
    
    return render_template('orders/detail.html', 
                          order=order,
                          items=items,
                          shipments=shipments)

# Shipment routes
@amazon_bp.route('/shipments/<int:shipment_id>')
@login_required
def shipment_detail(shipment_id):
    try:
        # Get the shipment object itself first to check ownership
        shipment = Shipment.query.options(
            db.joinedload(Shipment.order) # Load the order to check buyer_id
        ).get_or_404(shipment_id)

        # Check if user owns this order's shipment
        if shipment.order.buyer_id != current_user.user_id:
            flash('You do not have permission to view this shipment', 'error')
            return redirect(url_for('amazon.order_list'))

        # Get detailed shipment status using the service
        # This service method returns a dictionary, suitable for the template
        shipment_data = shipment_service.get_shipment_status(shipment_id) 
        
        if not shipment_data:
            # This case might be redundant due to get_or_404 above, but good for safety
            flash('Shipment not found or error retrieving details', 'error')
            return redirect(url_for('amazon.order_list'))

    except Exception as e:
         flash(f"Error loading shipment details: {e}", "error")
         return redirect(url_for('amazon.order_list'))

    return render_template('shipments/detail.html', 
                          shipment=shipment,          # Pass the Shipment model instance
                          shipment_data=shipment_data) # Pass the dictionary from the service

# *** ADDED: Route to handle address update ***
@amazon_bp.route('/shipments/<int:shipment_id>/update-address', methods=['POST'])
@login_required
def update_address(shipment_id):
    # Verify ownership first
    shipment = Shipment.query.options(db.joinedload(Shipment.order)).get_or_404(shipment_id)
    if shipment.order.buyer_id != current_user.user_id:
         flash('You do not have permission to modify this shipment.', 'error')
         return redirect(url_for('amazon.order_list'))

    destination_x = request.form.get('destination_x', type=int)
    destination_y = request.form.get('destination_y', type=int)

    if destination_x is None or destination_y is None:
        flash('Invalid coordinates provided.', 'error')
    else:
        success, message = shipment_service.update_delivery_address(
            shipment_id=shipment_id,
            destination_x=destination_x,
            destination_y=destination_y
        )
        if success:
            flash('Delivery address updated successfully!', 'success')
        else:
            flash(f'Failed to update address: {message}', 'error')
            
    # Redirect back to the order detail page where the shipment is listed
    return redirect(url_for('amazon.order_detail', order_id=shipment.order_id))


# --- Admin Routes ---
@admin_bp.route('/warehouses')
@login_required
def warehouses():
    # Check if user is admin/seller
    if not current_user.is_seller:
        flash('Access denied', 'error')
        return redirect(url_for('amazon.index'))
    
    try:
        warehouses_list = Warehouse.query.order_by(Warehouse.warehouse_id).all()
        
        # *** ADDED: Logic to get world connection status ***
        # This assumes you have a way to access the world_simulator instance
        # You might need to make world_simulator a global or app-context variable
        try:
             # Example: Accessing a potentially global simulator instance
             # Replace with your actual implementation
             global_world_simulator = current_app.extensions.get('world_simulator') 
             if global_world_simulator:
                  world_connected = global_world_simulator.connected
                  world_id = global_world_simulator.world_id
             else:
                  world_connected = False
                  world_id = None
        except Exception: # Handle cases where simulator isn't initialized/accessible
             world_connected = False
             world_id = None


        # Optional: Add product count to each warehouse object if needed by template
        # for wh in warehouses_list:
        #    wh.product_count = db.session.query(db.func.sum(WarehouseProduct.quantity)).filter_by(warehouse_id=wh.warehouse_id).scalar() or 0

    except Exception as e:
        flash(f"Error loading warehouses: {e}", "error")
        warehouses_list = []
        world_connected = False
        world_id = None

    return render_template('admin/warehouses.html', 
                          warehouses=warehouses_list,
                          world_connected=world_connected, # Pass status
                          world_id=world_id)             # Pass ID

# Adding a new warehouse
@admin_bp.route('/warehouses/add', methods=['GET', 'POST'])
@login_required
def add_warehouse():
    if not current_user.is_seller:
        flash('Access denied', 'error')
        return redirect(url_for('amazon.index'))
    
    if request.method == 'POST':
        x = request.form.get('x', type=int)
        y = request.form.get('y', type=int)
        
        # Basic validation for coordinates
        if x is None or y is None: # Check if conversion failed or value missing
            flash('Please provide valid integer coordinates for the warehouse', 'error')
            # *** ADDED: Pass existing warehouses back on error for map display ***
            existing_warehouses = Warehouse.query.order_by(Warehouse.warehouse_id).all()
            return render_template('admin/add_warehouse.html', existing_warehouses=existing_warehouses)
        
        # Optional: Add range validation if needed (e.g., 0-100)
        # if not (0 <= x <= 100 and 0 <= y <= 100):
        #     flash('Coordinates must be between 0 and 100.', 'error')
        #     existing_warehouses = Warehouse.query.order_by(Warehouse.warehouse_id).all()
        #     return render_template('admin/add_warehouse.html', existing_warehouses=existing_warehouses)
            
        warehouse_id = warehouse_service.initialize_warehouse(x, y)
        
        if warehouse_id:
            flash(f'Warehouse #{warehouse_id} added successfully at ({x}, {y})', 'success')
            return redirect(url_for('admin.warehouses'))
        else:
            flash('Failed to add warehouse. Check logs for details.', 'error')
            # Pass warehouses again in case of failure
            existing_warehouses = Warehouse.query.order_by(Warehouse.warehouse_id).all()
            return render_template('admin/add_warehouse.html', existing_warehouses=existing_warehouses)

    # GET Request
    # *** ADDED: Pass existing warehouses for map display ***
    try:
         existing_warehouses = Warehouse.query.order_by(Warehouse.warehouse_id).all()
    except Exception as e:
         flash(f"Error loading existing warehouses: {e}", 'error')
         existing_warehouses = []

    return render_template('admin/add_warehouse.html', existing_warehouses=existing_warehouses)


# Connecting to world simulator
@admin_bp.route('/connect-world', methods=['GET', 'POST'])
@login_required
def connect_world():
    if not current_user.is_seller:
        flash('Access denied', 'error')
        return redirect(url_for('amazon.index'))
    
    # *** Instantiate or get world simulator instance ***
    # Replace with how you manage your WorldSimulatorService instance
    world_simulator = WorldSimulatorService() 
    # Or get from app context/global: 
    # world_simulator = current_app.extensions.get('world_simulator')
    # if not world_simulator:
    #     flash("World simulator service not available.", "error")
    #     return redirect(url_for('admin.warehouses'))

    if request.method == 'POST':
        action = request.form.get('action') # Check if connecting or creating
        
        # Get selected warehouses for creation
        warehouse_ids_to_init = request.form.getlist('warehouse_ids', type=int)
        warehouses_to_init = Warehouse.query.filter(Warehouse.warehouse_id.in_(warehouse_ids_to_init)).all() if warehouse_ids_to_init else []

        if action == 'connect':
             world_id_to_connect = request.form.get('world_id', type=int)
             if world_id_to_connect is None:
                   flash('Please provide a World ID to connect.', 'error')
                   return redirect(url_for('admin.connect_world'))
             # Attempt connection (pass selected warehouses for potential init if needed by connect logic)
             # Note: Original spec says UPS creates world, Amazon connects. Adjust logic if needed.
             # The WorldSimulatorService connect method handles passing initwh data.
             connected_world_id, result = world_simulator.connect(world_id=world_id_to_connect, init_warehouses=warehouses_to_init)

        elif action == 'create':
            # Create new world (pass selected warehouses for initialization)
            # Pass None for world_id to signal creation
            connected_world_id, result = world_simulator.connect(world_id=None, init_warehouses=warehouses_to_init) 
        else:
            flash("Invalid action.", "error")
            return redirect(url_for('admin.connect_world'))

        # Handle connection result
        if result == "connected!":
            flash(f'Successfully connected to World ID: {connected_world_id}', 'success')
            
            # Update warehouses in DB with the world ID
            try:
                 all_warehouses = Warehouse.query.all() 
                 for w in all_warehouses:
                      w.world_id = connected_world_id
                 db.session.commit()
            except Exception as e:
                 db.session.rollback()
                 flash(f"Connected, but failed to update warehouse world IDs in database: {e}", "warning")

            # Store connection state if needed (e.g., in app context or global simulator instance)
            # Example: current_app.extensions['world_simulator'] = world_simulator
                 
            return redirect(url_for('admin.warehouses'))
        else:
            flash(f'Failed to connect to world simulator: {result}', 'error')
            return redirect(url_for('admin.connect_world'))

    # GET Request
    try:
         # *** ADDED: Pass current connection status and warehouses to template ***
         current_world_id = world_simulator.world_id if world_simulator.connected else None
         all_warehouses = Warehouse.query.order_by(Warehouse.warehouse_id).all()
    except Exception as e:
         flash(f"Error loading page data: {e}", "error")
         current_world_id = None
         all_warehouses = []

    return render_template('admin/connect_world.html', 
                          current_world_id=current_world_id,
                          warehouses=all_warehouses)

# --- API Routes ---
@api_bp.route('/products/search')
def api_product_search():
    """Search products and return JSON results"""
    search_query = request.args.get('query', '')
    category_id = request.args.get('category_id', type=int)
    limit = request.args.get('limit', 10, type=int)
    
    try:
        products_query = Product.query
        if search_query:
             products_query = products_query.filter(Product.product_name.ilike(f'%{search_query}%'))
        if category_id:
             products_query = products_query.filter(Product.category_id == category_id)
             
        products = products_query.limit(limit).all()
        
        results = [{
            'id': p.product_id,
            'name': p.product_name,
            'description': p.description,
            'price': float(p.price),
            'image': p.image or url_for('static', filename='images/default_product.png') # Example default image
        } for p in products]
        return jsonify(results)
    except Exception as e:
         # Log the error e
         return jsonify({'error': 'Failed to search products'}), 500


@api_bp.route('/warehouses')
@login_required # Consider if API key auth is more appropriate for some APIs
def api_warehouses():
    """Get list of warehouses"""
    try:
        warehouses = Warehouse.query.filter_by(active=True).all()
        results = [{
            'id': w.warehouse_id,
            'x': w.x,
            'y': w.y
        } for w in warehouses]
        return jsonify(results)
    except Exception as e:
         # Log the error e
         return jsonify({'error': 'Failed to retrieve warehouses'}), 500


@api_bp.route('/shipments/<int:shipment_id>/status')
@login_required
def api_shipment_status(shipment_id):
    try:
        # Get the shipment and verify ownership in one go
        shipment = Shipment.query.join(Order).filter(
            Shipment.shipment_id == shipment_id,
            Order.buyer_id == current_user.user_id # Ensure user owns the order
        ).first()

        if not shipment:
            return jsonify({'error': 'Shipment not found or permission denied'}), 404

        # Get detailed status using the service
        shipment_data = shipment_service.get_shipment_status(shipment_id)
        
        if not shipment_data:
            return jsonify({'error': 'Error retrieving shipment status details'}), 500
            
        return jsonify(shipment_data)
        
    except Exception as e:
         # Log the error e
         return jsonify({'error': 'Failed to retrieve shipment status'}), 500


@api_bp.route('/tracking/<tracking_id>')
def api_tracking(tracking_id):
    """Public endpoint to track shipment by UPS tracking ID"""
    try:
        shipment = Shipment.query.filter_by(ups_tracking_id=tracking_id).first()
        
        if not shipment:
            return jsonify({'error': 'Shipment not found for this tracking ID'}), 404
        
        shipment_data = shipment_service.get_shipment_status(shipment.shipment_id)
        if not shipment_data:
            return jsonify({'error': 'Error retrieving shipment status'}), 500
        
        # Maybe limit the data returned for public tracking?
        # public_data = { 'status': shipment_data.get('status'), ... }
        # return jsonify(public_data)
        
        return jsonify(shipment_data)
    except Exception as e:
         # Log the error e
         return jsonify({'error': 'Failed to track shipment'}), 500


# --- REMOVED Review Routes (Assuming they are handled by review_controller.py) ---
# from app.models.review import ReviewService
# @amazon_bp.route('/product/<int:product_id>/reviews')
# @amazon_bp.route('/seller/<int:seller_id>/reviews')
# --- End REMOVED Review Routes ---