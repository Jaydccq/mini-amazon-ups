from flask import Blueprint, request, jsonify, render_template, flash, redirect, url_for, current_app
from flask_login import login_required, current_user, login_user, logout_user
from app.model import db, Product, ProductCategory, Order, OrderProduct, User, Cart, CartProduct, Shipment, Warehouse
from app.services.warehouse_service import WarehouseService
from app.services.shipment_service import ShipmentService
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
from datetime import datetime
from app.models.review import ReviewService
from app.forms import LoginForm
amazon_bp = Blueprint('amazon', __name__)
api_bp = Blueprint('api', __name__, url_prefix='/api')
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

warehouse_service = WarehouseService()
shipment_service = ShipmentService()

@amazon_bp.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm() 
    if form.validate_on_submit(): 
        email = form.email.data
        password = form.password.data
        remember = form.remember_me.data

        user = User.query.filter_by(email=email).first()

        if not user or not user.check_password(password):
            flash('Invalid email or password', 'danger') 
            return render_template('login.html', title='Login', form=form) 

        login_user(user, remember=remember) # Use remember value

        if not user.cart:
             cart = Cart(user_id=user.user_id)
             db.session.add(cart)
             db.session.commit()

        next_page = request.args.get('next')
        return redirect(next_page or url_for('amazon.index'))

    return render_template('login.html', title='Login', form=form)

from app.forms import RegistrationForm

@amazon_bp.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm() 

    if form.validate_on_submit(): # This handles POST and validation
        existing_user = User.query.filter_by(email=form.email.data).first()
        if existing_user:
            flash('Email already registered', 'danger')
            return render_template('register.html', title='Register', form=form)

        new_user = User(
            email=form.email.data,
            first_name=form.firstname.data,
            last_name=form.lastname.data,
            address=form.address.data,
            is_seller=False # Assuming default is not a seller
        )
        new_user.set_password(form.password.data) # Use the model's method

        try:
            db.session.add(new_user)
            db.session.flush() # Flush to get the new_user.user_id

            cart = Cart(user_id=new_user.user_id)
            db.session.add(cart)
            
            db.session.commit()

            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('amazon.login'))
        except Exception as e:
             db.session.rollback()
             flash(f'An error occurred during registration: {e}', 'danger')

    return render_template('register.html', title='Register', form=form)

@amazon_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('amazon.index'))

@amazon_bp.route('/')
def index():
    products = Product.query.order_by(Product.created_at.desc()).limit(6).all()
    categories = ProductCategory.query.all()
    return render_template('index.html',
                          products=products,
                          categories=categories)

@amazon_bp.route('/products')
def product_list():
    search_query = request.args.get('search', '')
    category_id = request.args.get('category_id', type=int)
    sort_by = request.args.get('sort_by', 'name')
    sort_dir = request.args.get('sort_dir', 'asc')
    page = request.args.get('page', 1, type=int)

    per_page = 12
    products_query = Product.query

    if search_query:
        products_query = products_query.filter(
            Product.product_name.ilike(f'%{search_query}%') |
            Product.description.ilike(f'%{search_query}%')
        )

    if category_id:
        products_query = products_query.filter(Product.category_id == category_id)

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

    categories = ProductCategory.query.all()
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
    product = Product.query.get_or_404(product_id)
    inventory = warehouse_service.get_product_inventory(product_id)
    related_products = Product.query.filter(
        Product.category_id == product.category_id,
        Product.product_id != product.product_id
    ).limit(4).all()

    try:
        avg_rating, review_count = ReviewService.get_avg_rating_product(product_id)
        rating_distribution = ReviewService.get_rating_distribution(product_id)

        product.avg_rating = avg_rating if avg_rating is not None else 0
        product.review_count = review_count if review_count is not None else 0
        product.rating_distribution = rating_distribution if rating_distribution else {}

        if product.owner:
            product.owner_name = f"{product.owner.first_name} {product.owner.last_name}"
        else:
            product.owner_name = "Unknown Seller"

        if product.category:
            product.category_name = product.category.category_name
        else:
            product.category_name = "Uncategorized"

        product.warehouses = inventory

    except Exception as e:
        current_app.logger.error(f"Error fetching review/extra stats for product {product_id}: {e}")
        product.avg_rating = 0
        product.review_count = 0
        product.rating_distribution = {}
        product.owner_name = "Error fetching seller"
        product.category_name = "Error fetching category"
        product.warehouses = []

    return render_template('product_detail.html',
                           product=product,
                           related_products=related_products)


@amazon_bp.route('/cart')
@login_required
def cart():
    cart = Cart.query.filter_by(user_id=current_user.user_id).first()

    if not cart:
        cart = Cart(user_id=current_user.user_id)
        db.session.add(cart)
        db.session.commit()

    cart_items = CartProduct.query.filter_by(cart_id=cart.cart_id).all()
    total = sum(item.quantity * item.price_at_addition for item in cart_items)

    return render_template('cart.html',
                          cart=cart,
                          cart_items=cart_items,
                          total=total)

@amazon_bp.route('/cart/add', methods=['POST'])
@login_required
def add_to_cart():
    product_id = request.form.get('product_id', type=int)
    seller_id = request.form.get('seller_id', type=int) # Get seller_id from form
    quantity = request.form.get('quantity', 1, type=int)

    if not product_id or not seller_id or quantity <= 0:
        flash('Invalid product, seller or quantity', 'error')
        return redirect(request.referrer or url_for('amazon.index'))

    product = Product.query.get(product_id)
    if not product:
        flash('Product not found', 'error')
        return redirect(request.referrer or url_for('amazon.index'))

    # Use the seller_id from the form if provided, otherwise default to product owner
    actual_seller_id = seller_id if seller_id else product.owner_id

    cart = Cart.query.filter_by(user_id=current_user.user_id).first()
    if not cart:
        cart = Cart(user_id=current_user.user_id)
        db.session.add(cart)
        db.session.flush()

    cart_product = CartProduct.query.filter_by(
        cart_id=cart.cart_id,
        product_id=product_id,
        seller_id=actual_seller_id # Use the determined seller_id
    ).first()

    if cart_product:
        cart_product.quantity += quantity
    else:
        cart_product = CartProduct(
            cart_id=cart.cart_id,
            product_id=product_id,
            seller_id=actual_seller_id, # Use the determined seller_id
            quantity=quantity,
            price_at_addition=product.price
        )
        db.session.add(cart_product)

    db.session.commit()
    flash(f'Added {quantity} of {product.product_name} to your cart', 'success')
    # Redirect back to the product page or cart
    return redirect(request.referrer or url_for('amazon.cart'))


@amazon_bp.route('/cart/update', methods=['POST'])
@login_required
def update_cart():
    cart_id = request.form.get('cart_id', type=int)
    product_id = request.form.get('product_id', type=int)
    seller_id = request.form.get('seller_id', type=int)
    quantity = request.form.get('quantity', type=int)

    if not all([cart_id, product_id, seller_id]) or quantity is None:
        flash('Invalid request', 'error')
        return redirect(url_for('amazon.cart'))

    cart_product = CartProduct.query.filter_by(
        cart_id=cart_id,
        product_id=product_id,
        seller_id=seller_id
    ).first()

    if not cart_product:
        flash('Product not found in cart', 'error')
        return redirect(url_for('amazon.cart'))

    if quantity <= 0:
        db.session.delete(cart_product)
    else:
        cart_product.quantity = quantity

    db.session.commit()
    flash('Cart updated successfully', 'success')
    return redirect(url_for('amazon.cart'))

@amazon_bp.route('/cart/remove', methods=['POST'])
@login_required
def remove_from_cart():
    cart_id = request.form.get('cart_id', type=int)
    product_id = request.form.get('product_id', type=int)
    seller_id = request.form.get('seller_id', type=int)

    if not all([cart_id, product_id, seller_id]):
        flash('Invalid request', 'error')
        return redirect(url_for('amazon.cart'))

    cart_product = CartProduct.query.filter_by(
        cart_id=cart_id,
        product_id=product_id,
        seller_id=seller_id
    ).first()

    if not cart_product:
        flash('Product not found in cart', 'error')
        return redirect(url_for('amazon.cart'))

    db.session.delete(cart_product)
    db.session.commit()

    flash('Product removed from cart', 'success')
    return redirect(url_for('amazon.cart'))

@amazon_bp.route('/orders')
@login_required
def order_list():
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status')

    per_page = 10
    orders_query = Order.query.filter_by(buyer_id=current_user.user_id)

    if status:
        orders_query = orders_query.filter(Order.order_status == status)

    orders_query = orders_query.order_by(Order.order_date.desc())
    orders = orders_query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template('orders/list.html',
                          orders=orders.items,
                          pagination=orders,
                          status=status)

@amazon_bp.route('/orders/<int:order_id>')
@login_required
def order_detail(order_id):
    order = Order.query.get_or_404(order_id)

    if order.buyer_id != current_user.user_id:
        flash('You do not have permission to view this order', 'error')
        return redirect(url_for('amazon.order_list'))

    items = OrderProduct.query.filter_by(order_id=order_id).all()
    shipments = Shipment.query.filter_by(order_id=order_id).all()

    return render_template('orders/detail.html',
                          order=order,
                          items=items,
                          shipments=shipments)

@amazon_bp.route('/shipments/<int:shipment_id>')
@login_required
def shipment_detail(shipment_id):
    shipment_data = shipment_service.get_shipment_status(shipment_id)

    if not shipment_data:
        flash('Shipment not found', 'error')
        return redirect(url_for('amazon.order_list'))

    shipment = Shipment.query.get_or_404(shipment_id)
    order = Order.query.get_or_404(shipment.order_id)

    if order.buyer_id != current_user.user_id:
        flash('You do not have permission to view this shipment', 'error')
        return redirect(url_for('amazon.order_list'))

    return render_template('shipments/detail.html',
                          shipment=shipment,
                          shipment_data=shipment_data)


@amazon_bp.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    cart = Cart.query.filter_by(user_id=current_user.user_id).first()

    if not cart or not cart.items:
        flash('Your cart is empty', 'error')
        return redirect(url_for('amazon.cart'))

    total = sum(item.quantity * item.price_at_addition for item in cart.items)

    if request.method == 'POST':
        destination_x = request.form.get('destination_x', type=int)
        destination_y = request.form.get('destination_y', type=int)
        ups_account = request.form.get('ups_account')
        warehouse_id = request.form.get('warehouse_id', type=int)

        if destination_x is None or destination_y is None:
            flash('Please provide delivery coordinates', 'error')
            return redirect(url_for('amazon.checkout'))

        if not warehouse_id:
            warehouse = warehouse_service.get_nearest_warehouse(destination_x, destination_y)
            if warehouse:
                warehouse_id = warehouse.warehouse_id
            else:
                flash('No warehouse available for delivery', 'error')
                return redirect(url_for('amazon.checkout'))

        success, result = Cart.checkout_cart(current_user.user_id)

        if success:
            order_id = result
            shipment_success, shipment_id_or_error = shipment_service.create_shipment(
                order_id=order_id,
                warehouse_id=warehouse_id,
                destination_x=destination_x,
                destination_y=destination_y,
                ups_account=ups_account
            )

            if shipment_success:
                flash(f'Order placed successfully! Shipment ID: {shipment_id_or_error}', 'success')
                return redirect(url_for('amazon.order_detail', order_id=order_id))
            else:
                flash(f'Order placed, but shipment creation failed: {shipment_id_or_error}', 'warning')
                return redirect(url_for('amazon.order_detail', order_id=order_id))
        else:
            flash(f'Checkout failed: {result}', 'error')
            return redirect(url_for('amazon.cart'))

    warehouses = Warehouse.query.filter_by(active=True).all()

    # Prepare cart items data for the template
    cart_items_data = []
    for item in cart.items:
        product = Product.query.get(item.product_id)
        seller = User.query.get(item.seller_id)
        cart_items_data.append({
            'product_id': item.product_id,
            'product_name': product.product_name if product else 'N/A',
            'quantity': item.quantity,
            'price': item.price_at_addition,
            'seller_id': item.seller_id,
            'seller_name': f"{seller.first_name} {seller.last_name}" if seller else 'N/A',
            'total_price': item.quantity * item.price_at_addition
        })


    return render_template('checkout.html',
                        #   cart=cart, # No longer needed if using cart_items_data
                          cart_items=cart_items_data, # Pass processed list
                          total=total,
                          warehouses=warehouses)

@amazon_bp.route('/orders/<int:order_id>/update_address/<int:shipment_id>', methods=['POST'])
@login_required
def update_address(order_id, shipment_id):
    destination_x = request.form.get('destination_x', type=int)
    destination_y = request.form.get('destination_y', type=int)

    if destination_x is None or destination_y is None:
        flash('Invalid coordinates provided.', 'danger')
        return redirect(url_for('amazon.order_detail', order_id=order_id))

    shipment = Shipment.query.filter_by(shipment_id=shipment_id, order_id=order_id).first_or_404()
    order = Order.query.get_or_404(order_id)

    if order.buyer_id != current_user.user_id:
        flash('You do not have permission to modify this shipment.', 'danger')
        return redirect(url_for('amazon.order_detail', order_id=order_id))

    success, message = shipment_service.update_delivery_address(shipment_id, destination_x, destination_y)

    if success:
        flash('Delivery address updated successfully!', 'success')
    else:
        flash(f'Failed to update address: {message}', 'danger')

    return redirect(url_for('amazon.order_detail', order_id=order_id))


@admin_bp.route('/warehouses')
@login_required
def warehouses():
    if not current_user.is_seller:
        flash('Access denied', 'error')
        return redirect(url_for('amazon.index'))

    warehouses = Warehouse.query.all()

    return render_template('admin/warehouses.html',
                          warehouses=warehouses)

@admin_bp.route('/warehouses/add', methods=['GET', 'POST'])
@login_required
def add_warehouse():
    if not current_user.is_seller:
        flash('Access denied', 'error')
        return redirect(url_for('amazon.index'))

    if request.method == 'POST':
        x = request.form.get('x', type=int)
        y = request.form.get('y', type=int)

        if x is None or y is None :
            flash('Please provide warehouse coordinates', 'error')
            return redirect(url_for('admin.add_warehouse'))

        warehouse_id = warehouse_service.initialize_warehouse(x, y)

        if warehouse_id:
            flash('Warehouse added successfully', 'success')
            return redirect(url_for('admin.warehouses'))
        else:
            flash('Failed to add warehouse', 'error')
            return redirect(url_for('admin.add_warehouse'))

    existing_warehouses = Warehouse.query.all()
    return render_template('admin/add_warehouse.html', existing_warehouses=existing_warehouses)

@admin_bp.route('/connect-world', methods=['GET', 'POST'])
@login_required
def connect_world():
    if not current_user.is_seller:
        flash('Access denied', 'error')
        return redirect(url_for('amazon.index'))

    world_simulator = current_app.config.get('WORLD_SIMULATOR_SERVICE')
    if not world_simulator:
         from app.services.world_simulator_service import WorldSimulatorService
         world_simulator = WorldSimulatorService(app=current_app)
         current_app.config['WORLD_SIMULATOR_SERVICE'] = world_simulator


    if request.method == 'POST':
        action = request.form.get('action')
        world_id = request.form.get('world_id')
        warehouse_ids = request.form.getlist('warehouse_ids')
        sim_speed = request.form.get('sim_speed', 100, type=int)


        init_warehouses = []
        if action == 'create' and warehouse_ids:
            init_warehouses = Warehouse.query.filter(Warehouse.warehouse_id.in_(warehouse_ids)).all()
        elif action == 'connect' and world_id:
            world_id = int(world_id) # Ensure world_id is int if connecting
        else:
             # Determine which field was missing or invalid
            if action == 'connect' and not world_id:
                 flash('Please provide a World ID to connect.', 'warning')
            elif action == 'create' and not warehouse_ids:
                 flash('Please select at least one warehouse to initialize.', 'warning')
            else:
                 flash('Invalid request.', 'danger')
            return redirect(url_for('admin.connect_world'))


        if action == 'create':
            world_id_to_connect = None
        else: # action == 'connect'
            world_id_to_connect = world_id


        connected_world_id, result = world_simulator.connect(world_id=world_id_to_connect, init_warehouses=init_warehouses)

        if connected_world_id:
            flash(f'Connected to world simulator: {result} (World ID: {connected_world_id})', 'success')

            # Update all active warehouses with the new world_id
            active_warehouses = Warehouse.query.filter_by(active=True).all()
            for w in active_warehouses:
                w.world_id = connected_world_id
            db.session.commit()

            # Optionally set simulation speed
            if sim_speed != 100: # Only set if different from default
                speed_set = world_simulator.set_sim_speed(sim_speed)
                if speed_set:
                     flash(f'Simulation speed set to {sim_speed}.', 'info')
                else:
                     flash('Failed to set simulation speed.', 'warning')


            current_app.config['CURRENT_WORLD_ID'] = connected_world_id
            return redirect(url_for('admin.warehouses'))
        else:
            flash(f'Failed to connect to world simulator: {result}', 'error')
            return redirect(url_for('admin.connect_world'))

    current_world_id = current_app.config.get('CURRENT_WORLD_ID')
    warehouses = Warehouse.query.filter_by(active=True).all()
    return render_template('admin/connect_world.html',
                           current_world_id=current_world_id,
                           warehouses=warehouses,
                           world_connected=world_simulator.connected) # Pass connection status


@admin_bp.route('/disconnect-world', methods=['POST'])
@login_required
def disconnect_world():
     if not current_user.is_seller:
         flash('Access denied', 'error')
         return redirect(url_for('amazon.index'))

     world_simulator = current_app.config.get('WORLD_SIMULATOR_SERVICE')
     if world_simulator and world_simulator.connected:
          world_simulator.disconnect()
          current_app.config['CURRENT_WORLD_ID'] = None # Clear stored world ID
          flash('Disconnected from World Simulator.', 'success')
     else:
          flash('Not connected to any world.', 'warning')

     return redirect(url_for('admin.connect_world'))


@api_bp.route('/products/search')
def api_product_search():
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
    warehouses = Warehouse.query.filter_by(active=True).all()

    return jsonify([{
        'id': w.warehouse_id,
        'x': w.x,
        'y': w.y
    } for w in warehouses])

@api_bp.route('/shipments/<int:shipment_id>/status')
@login_required
def api_shipment_status(shipment_id):
    shipment_data = shipment_service.get_shipment_status(shipment_id)

    if not shipment_data:
        return jsonify({'error': 'Shipment not found'}), 404

    shipment = Shipment.query.get_or_404(shipment_id)
    order = Order.query.get_or_404(shipment.order_id)

    if order.buyer_id != current_user.user_id and not current_user.is_seller:
        return jsonify({'error': 'Permission denied'}), 403

    return jsonify(shipment_data)


@api_bp.route('/tracking/<tracking_id>')
def api_tracking(tracking_id):
    shipment = Shipment.query.filter_by(ups_tracking_id=tracking_id).first()

    if not shipment:
        return jsonify({'error': 'Shipment not found'}), 404

    shipment_data = shipment_service.get_shipment_status(shipment.shipment_id)
    if not shipment_data:
        return jsonify({'error': 'Error retrieving shipment status'}), 500

    return jsonify(shipment_data)


@amazon_bp.route('/product/<int:product_id>/reviews')
def product_reviews(product_id):
    product = Product.query.get_or_404(product_id)
    reviews = ReviewService.get_product_reviews(product_id)
    avg_rating, review_count = ReviewService.get_avg_rating_product(product_id)
    rating_distribution = ReviewService.get_rating_distribution(product_id)

    return render_template('product/reviews.html',
                          product=product,
                          reviews=reviews,
                          avg_rating=avg_rating,
                          review_count=review_count,
                          rating_distribution=rating_distribution)


@amazon_bp.route('/seller/<int:seller_id>/reviews')
def seller_reviews(seller_id):
    seller = User.query.get_or_404(seller_id)
    # Assuming get_seller_reviews exists and returns review objects
    reviews = ReviewService.get_seller_reviews(seller_id)
    # Assuming get_avg_rating_seller exists
    avg_rating, review_count = ReviewService.get_avg_rating_seller(seller_id)
    # Assuming get_rating_distribution_seller exists
    rating_distribution = ReviewService.get_rating_distribution_seller(seller_id)

    return render_template('seller/reviews.html',
                           seller=seller,
                           reviews=reviews,
                           avg_rating=avg_rating,
                           review_count=review_count,
                           rating_distribution=rating_distribution)


@amazon_bp.route('/profile')
@login_required
def profile():

    return render_template('profile.html', user=current_user)

from app.forms import EditProfileForm
@amazon_bp.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    user = db.session.get(User, current_user.user_id)
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('amazon.index'))

    # Instantiate the form
    form = EditProfileForm()

    if form.validate_on_submit():

        user.first_name = form.first_name.data
        user.last_name = form.last_name.data
        user.address = form.address.data
        # Note: Email and password changes are not handled here

        try:
            db.session.commit()
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('amazon.profile')) # Redirect back to the profile view
        except Exception as e:
            db.session.rollback()
            flash(f'An error occurred while updating profile: {e}', 'danger')
            current_app.logger.error(f"Error updating profile for user {user.user_id}: {e}")

    # For GET requests (or if form validation fails on POST)
    # Populate the form fields with the user's current data
    elif request.method == 'GET':
        form.first_name.data = user.first_name
        form.last_name.data = user.last_name
        form.address.data = user.address

    return render_template('edit_profile.html', user=user, form=form)
