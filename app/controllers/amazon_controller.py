from flask import Blueprint, request, jsonify, render_template, flash, redirect, url_for, current_app
from flask_login import login_required, current_user, login_user, logout_user
from app.model import db, Product, ProductCategory, Order, OrderProduct, User, Cart, CartProduct, Shipment, Warehouse
from app.services.warehouse_service import WarehouseService
from app.services.shipment_service import ShipmentService
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
from datetime import datetime

# Create blueprints
amazon_bp = Blueprint('amazon', __name__)
api_bp = Blueprint('api', __name__, url_prefix='/api')
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# Initialize services
warehouse_service = WarehouseService()
shipment_service = ShipmentService()

# Authentication routes
@amazon_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login"""
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not email or not password:
            flash('Please provide email and password', 'error')
            return render_template('login.html')
        
        user = User.query.filter_by(email=email).first()
        
        if not user or not user.check_password(password):
            flash('Invalid email or password', 'error')
            return render_template('login.html')
        
        login_user(user)
        
        # Create cart if user doesn't have one
        if not user.cart:
            cart = Cart(user_id=user.user_id)
            db.session.add(cart)
            db.session.commit()
        
        next_page = request.args.get('next')
        return redirect(next_page or url_for('amazon.index'))
    
    return render_template('login.html')

@amazon_bp.route('/register', methods=['GET', 'POST'])
def register():
    """User registration"""
    if request.method == 'POST':
        email = request.form.get('email')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        password = request.form.get('password')
        
        if not email or not first_name or not last_name or not password:
            flash('Please fill in all required fields', 'error')
            return render_template('register.html')
        
        existing_user = User.query.filter_by(email=email).first()
        
        if existing_user:
            flash('Email already registered', 'error')
            return render_template('register.html')
        
        # Create new user
        new_user = User(
            email=email,
            first_name=first_name,
            last_name=last_name
        )
        new_user.set_password(password)
        
        db.session.add(new_user)
        db.session.commit()
        
        # Create cart for the new user
        cart = Cart(user_id=new_user.user_id)
        db.session.add(cart)
        db.session.commit()
        
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('amazon.login'))
    
    return render_template('register.html')

@amazon_bp.route('/logout')
@login_required
def logout():
    """User logout"""
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('amazon.index'))

# Main routes
@amazon_bp.route('/')
def index():
    """Homepage"""
    # Get featured products
    products = Product.query.order_by(Product.created_at.desc()).limit(6).all()
    
    # Get product categories
    categories = ProductCategory.query.all()
    
    return render_template('index.html', 
                          products=products,
                          categories=categories)

# Product routes
@amazon_bp.route('/products')
def product_list():
    """List all products"""
    search_query = request.args.get('search', '')
    category_id = request.args.get('category_id', type=int)
    sort_by = request.args.get('sort_by', 'name')
    sort_dir = request.args.get('sort_dir', 'asc')
    page = request.args.get('page', 1, type=int)
    
    # Get products with filters and pagination
    per_page = 12
    products_query = Product.query
    
    # Apply search filter
    if search_query:
        products_query = products_query.filter(
            Product.product_name.ilike(f'%{search_query}%') | 
            Product.description.ilike(f'%{search_query}%')
        )
    
    # Apply category filter
    if category_id:
        products_query = products_query.filter(Product.category_id == category_id)
    
    # Apply sorting
    if sort_by == 'name':
        if sort_dir == 'asc':
            products_query = products_query.order_by(Product.product_name.asc())
        else:
            products_query = products_query.order_by(Product.product_name.desc())
    elif sort_by == 'price':
        if sort_dir == 'asc':
            products_query = products_query.order_by(Product.price.asc())
        else:
            products_query = products_query.order_by(Product.price.desc())
    elif sort_by == 'newest':
        products_query = products_query.order_by(Product.created_at.desc())
    
    # Get categories for sidebar
    categories = ProductCategory.query.all()
    
    # Paginate results
    products = products_query.paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('products/list.html', 
                          products=products.items,
                          pagination=products,
                          categories=categories,
                          search_query=search_query,
                          category_id=category_id,
                          sort_by=sort_by,
                          sort_dir=sort_dir)

@amazon_bp.route('/products/<int:product_id>')
def product_detail(product_id):
    """Show detailed product information"""
    product = Product.query.get_or_404(product_id)
    
    # Get warehouse inventory for this product
    inventory = warehouse_service.get_product_inventory(product_id)
    
    # Get related products
    related_products = Product.query.filter(
        Product.category_id == product.category_id,
        Product.product_id != product.product_id
    ).limit(4).all()
    
    return render_template('products/detail.html', 
                          product=product,
                          inventory=inventory,
                          related_products=related_products)

# Cart routes
@amazon_bp.route('/cart')
@login_required
def cart():
    """Show shopping cart"""
    cart = Cart.query.filter_by(user_id=current_user.user_id).first()
    
    if not cart:
        cart = Cart(user_id=current_user.user_id)
        db.session.add(cart)
        db.session.commit()
    
    # Get cart items with product details
    cart_items = CartProduct.query.filter_by(cart_id=cart.cart_id).all()
    
    # Calculate total
    total = sum(item.quantity * item.price_at_addition for item in cart_items)
    
    return render_template('cart.html', 
                          cart=cart,
                          cart_items=cart_items,
                          total=total)

@amazon_bp.route('/cart/add', methods=['POST'])
@login_required
def add_to_cart():
    """Add a product to the cart"""
    product_id = request.form.get('product_id', type=int)
    quantity = request.form.get('quantity', 1, type=int)
    
    if not product_id or quantity <= 0:
        flash('Invalid product or quantity', 'error')
        return redirect(url_for('amazon.cart'))
    
    # Get the product
    product = Product.query.get_or_404(product_id)
    
    # Get or create cart
    cart = Cart.query.filter_by(user_id=current_user.user_id).first()
    if not cart:
        cart = Cart(user_id=current_user.user_id)
        db.session.add(cart)
        db.session.flush()
    
    # Check if product already in cart
    cart_product = CartProduct.query.filter_by(
        cart_id=cart.cart_id,
        product_id=product_id,
        seller_id=product.owner_id
    ).first()
    
    if cart_product:
        # Update quantity
        cart_product.quantity += quantity
    else:
        # Add new item to cart
        cart_product = CartProduct(
            cart_id=cart.cart_id,
            product_id=product_id,
            seller_id=product.owner_id,
            quantity=quantity,
            price_at_addition=product.price
        )
        db.session.add(cart_product)
    
    db.session.commit()
    
    flash(f'Added {quantity} of {product.product_name} to your cart', 'success')
    return redirect(url_for('amazon.cart'))

@amazon_bp.route('/cart/update', methods=['POST'])
@login_required
def update_cart():
    """Update cart quantities"""
    cart_id = request.form.get('cart_id', type=int)
    product_id = request.form.get('product_id', type=int)
    seller_id = request.form.get('seller_id', type=int)
    quantity = request.form.get('quantity', type=int)
    
    if not all([cart_id, product_id, seller_id]) or quantity is None:
        flash('Invalid request', 'error')
        return redirect(url_for('amazon.cart'))
    
    # Get cart product
    cart_product = CartProduct.query.filter_by(
        cart_id=cart_id,
        product_id=product_id,
        seller_id=seller_id
    ).first()
    
    if not cart_product:
        flash('Product not found in cart', 'error')
        return redirect(url_for('amazon.cart'))
    
    if quantity <= 0:
        # Remove from cart
        db.session.delete(cart_product)
    else:
        # Update quantity
        cart_product.quantity = quantity
    
    db.session.commit()
    
    flash('Cart updated successfully', 'success')
    return redirect(url_for('amazon.cart'))

@amazon_bp.route('/cart/remove', methods=['POST'])
@login_required
def remove_from_cart():
    """Remove a product from the cart"""
    cart_id = request.form.get('cart_id', type=int)
    product_id = request.form.get('product_id', type=int)
    seller_id = request.form.get('seller_id', type=int)
    
    if not all([cart_id, product_id, seller_id]):
        flash('Invalid request', 'error')
        return redirect(url_for('amazon.cart'))
    
    # Get cart product
    cart_product = CartProduct.query.filter_by(
        cart_id=cart_id,
        product_id=product_id,
        seller_id=seller_id
    ).first()
    
    if not cart_product:
        flash('Product not found in cart', 'error')
        return redirect(url_for('amazon.cart'))
    
    # Remove from cart
    db.session.delete(cart_product)
    db.session.commit()
    
    flash('Product removed from cart', 'success')
    return redirect(url_for('amazon.cart'))

# Order routes
@amazon_bp.route('/orders')
@login_required
def order_list():
    """List user's orders"""
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status')
    
    # Get orders with filters and pagination
    per_page = 10
    orders_query = Order.query.filter_by(buyer_id=current_user.user_id)
    
    if status:
        orders_query = orders_query.filter(Order.order_status == status)
    
    orders_query = orders_query.order_by(Order.order_date.desc())
    
    # Paginate results
    orders = orders_query.paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('orders/list.html', 
                          orders=orders.items,
                          pagination=orders,
                          status=status)

@amazon_bp.route('/orders/<int:order_id>')
@login_required
def order_detail(order_id):
    """Show detailed order information"""
    order = Order.query.get_or_404(order_id)
    
    # Check if user owns this order
    if order.buyer_id != current_user.user_id:
        flash('You do not have permission to view this order', 'error')
        return redirect(url_for('amazon.order_list'))
    
    # Get order items
    items = OrderProduct.query.filter_by(order_id=order_id).all()
    
    # Get shipments for this order
    shipments = Shipment.query.filter_by(order_id=order_id).all()
    
    return render_template('orders/detail.html', 
                          order=order,
                          items=items,
                          shipments=shipments)

# Shipment routes
@amazon_bp.route('/shipments/<int:shipment_id>')
@login_required
def shipment_detail(shipment_id):
    """Show detailed shipment information"""
    # Get shipment details
    shipment_data = shipment_service.get_shipment_status(shipment_id)
    
    if not shipment_data:
        flash('Shipment not found', 'error')
        return redirect(url_for('amazon.order_list'))
    
    # Get the shipment to check ownership
    shipment = Shipment.query.get_or_404(shipment_id)
    order = Order.query.get_or_404(shipment.order_id)
    
    # Check if user owns this order's shipment
    if order.buyer_id != current_user.user_id:
        flash('You do not have permission to view this shipment', 'error')
        return redirect(url_for('amazon.order_list'))
    
    return render_template('shipments/detail.html', 
                          shipment=shipment,
                          shipment_data=shipment_data)

# Checkout process
@amazon_bp.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    """Checkout process with destination selection"""
    # Get user's cart
    cart = Cart.query.filter_by(user_id=current_user.user_id).first()
    
    if not cart or not cart.items:
        flash('Your cart is empty', 'error')
        return redirect(url_for('amazon.cart'))
    
    # Calculate total
    total = sum(item.quantity * item.price_at_addition for item in cart.items)
    
    if request.method == 'POST':
        # Process form data
        destination_x = request.form.get('destination_x', type=int)
        destination_y = request.form.get('destination_y', type=int)
        ups_account = request.form.get('ups_account')
        warehouse_id = request.form.get('warehouse_id', type=int)
        
        if not destination_x or not destination_y:
            flash('Please provide delivery coordinates', 'error')
            return redirect(url_for('amazon.checkout'))
        
        if not warehouse_id:
            # Find nearest warehouse
            warehouse = warehouse_service.get_nearest_warehouse(destination_x, destination_y)
            if warehouse:
                warehouse_id = warehouse.warehouse_id
            else:
                flash('No warehouse available for delivery', 'error')
                return redirect(url_for('amazon.checkout'))
        
        # Process checkout from cart
        success, result = Cart.checkout_cart(current_user.user_id)
        
        if success:
            order_id = result
            # Create shipment for the order
            shipment_success, shipment_result = shipment_service.create_shipment(
                order_id=order_id,
                warehouse_id=warehouse_id,
                destination_x=destination_x,
                destination_y=destination_y,
                ups_account=ups_account
            )
            
            if shipment_success:
                flash(f'Order placed successfully! Tracking number: {shipment_result}', 'success')
                return redirect(url_for('amazon.order_detail', order_id=order_id))
            else:
                flash(f'Order placed, but shipment creation failed: {shipment_result}', 'warning')
                return redirect(url_for('amazon.order_detail', order_id=order_id))
        else:
            flash(f'Checkout failed: {result}', 'error')
            return redirect(url_for('amazon.cart'))
    
    # GET request - show checkout form
    warehouses = Warehouse.query.filter_by(active=True).all()
    
    return render_template('checkout.html', 
                          cart=cart,
                          cart_items=cart.items,
                          total=total,
                          warehouses=warehouses)

# Admin routes for warehouse management
@admin_bp.route('/warehouses')
@login_required
def warehouses():
    """Admin view for warehouse management"""
    # Check if user is admin
    if not current_user.is_seller:
        flash('Access denied', 'error')
        return redirect(url_for('amazon.index'))
    
    warehouses = Warehouse.query.all()
    
    return render_template('admin/warehouses.html', 
                          warehouses=warehouses)

@admin_bp.route('/warehouses/add', methods=['GET', 'POST'])
@login_required
def add_warehouse():
    """Add a new warehouse"""
    # Check if user is admin
    if not current_user.is_seller:
        flash('Access denied', 'error')
        return redirect(url_for('amazon.index'))
    
    if request.method == 'POST':
        # Process form data
        x = request.form.get('x', type=int)
        y = request.form.get('y', type=int)
        
        if not x or not y:
            flash('Please provide warehouse coordinates', 'error')
            return redirect(url_for('admin.add_warehouse'))
        
        # Create warehouse
        warehouse_id = warehouse_service.initialize_warehouse(x, y)
        
        if warehouse_id:
            flash('Warehouse added successfully', 'success')
            return redirect(url_for('admin.warehouses'))
        else:
            flash('Failed to add warehouse', 'error')
            return redirect(url_for('admin.add_warehouse'))
    
    return render_template('admin/add_warehouse.html')

@admin_bp.route('/connect-world', methods=['GET', 'POST'])
@login_required
def connect_world():
    """Connect to world simulator"""
    # Check if user is admin
    if not current_user.is_seller:
        flash('Access denied', 'error')
        return redirect(url_for('amazon.index'))
    
    if request.method == 'POST':
        # Process form data
        world_id = request.form.get('world_id', type=int)
        
        # Initialize world simulator service
        from app.services.world_simulator_service import WorldSimulatorService
        world_simulator = WorldSimulatorService()
        
        # Get all warehouses for initialization
        warehouses = Warehouse.query.filter_by(active=True).all()
        
        # Connect to world simulator
        world_id, result = world_simulator.connect(world_id, warehouses)
        
        if world_id:
            flash(f'Connected to world simulator: {result}', 'success')
            
            # Update all warehouses with world ID
            for w in Warehouse.query.filter_by(active=True).all():
                w.world_id = world_id
            db.session.commit()
            
            return redirect(url_for('admin.warehouses'))
        else:
            flash(f'Failed to connect to world simulator: {result}', 'error')
            return redirect(url_for('admin.connect_world'))
    
    return render_template('admin/connect_world.html')

# API routes for AJAX calls
@api_bp.route('/products/search')
def api_product_search():
    """Search products and return JSON results"""
    search_query = request.args.get('query', '')
    category_id = request.args.get('category_id', type=int)
    limit = request.args.get('limit', 10, type=int)
    
    products = Product.query.filter(
        Product.product_name.ilike(f'%{search_query}%') if search_query else True,
        Product.category_id == category_id if category_id else True
    ).limit(limit).all()
    
    return jsonify([{
        'id': p.product_id,
        'name': p.product_name,
        'description': p.description,
        'price': float(p.price),
        'image': p.image
    } for p in products])

@api_bp.route('/warehouses')
@login_required
def api_warehouses():
    """Get list of warehouses"""
    warehouses = Warehouse.query.filter_by(active=True).all()
    
    return jsonify([{
        'id': w.warehouse_id,
        'x': w.x,
        'y': w.y
    } for w in warehouses])

@api_bp.route('/shipments/<int:shipment_id>/status')
@login_required
def api_shipment_status(shipment_id):
    """Get current shipment status"""
    shipment_data = shipment_service.get_shipment_status(shipment_id)
    
    if not shipment_data:
        return jsonify({'error': 'Shipment not found'}), 404
    
    # Check if user owns this shipment
    shipment = Shipment.query.get_or_404(shipment_id)
    order = Order.query.get_or_404(shipment.order_id)
    
    if order.buyer_id != current_user.user_id:
        return jsonify({'error': 'Permission denied'}), 403
    
    return jsonify(shipment_data)

@api_bp.route('/tracking/<tracking_id>')
def api_tracking(tracking_id):
    """Get shipment status by tracking ID"""
    shipment = Shipment.query.filter_by(ups_tracking_id=tracking_id).first()
    
    if not shipment:
        return jsonify({'error': 'Shipment not found'}), 404
    
    shipment_data = shipment_service.get_shipment_status(shipment.shipment_id)
    if not shipment_data:
        return jsonify({'error': 'Error retrieving shipment status'}), 500
    
    return jsonify(shipment_data)