# app/controllers/cart_controller.py
from flask import Blueprint, request, redirect, url_for, flash, render_template, current_app as app
from flask_login import login_required, current_user
from app.models.cart import Cart
from app.models.inventory import Inventory
from app.services.warehouse_service import WarehouseService
from app.services.shipment_service import ShipmentService

bp = Blueprint("cart", __name__, url_prefix="/cart")

@bp.route('/', methods=["GET"])
@login_required
def view_cart():
    try:
        cart_items = Cart.get_cart_items(current_user.id)
        total_cart_value = sum(item[7] for item in cart_items) if cart_items else 0

        return render_template('cart.html',
                              cart_items=cart_items,
                              total_cart_value=total_cart_value)
    except Exception as e:
        print(f"Error retrieving cart: {e}")
        flash("An error occurred while retrieving your cart", "danger")
        return redirect(url_for('index.index'))

@bp.route("/add", methods=["POST"])
@login_required
def add_to_cart():
    product_id = request.form.get("product_id")
    seller_id = request.form.get("seller_id")
    quantity = int(request.form.get("quantity", 1))

    if not product_id or not seller_id:
        flash("Invalid product information", "danger")
        return redirect(request.referrer or url_for('index.index'))

    try:
        inventory = Inventory.get_by_seller_and_product(seller_id, product_id)
        if not inventory or inventory.quantity < quantity:
            flash("This product is out of stock or not available in the requested quantity", "warning")
            return redirect(request.referrer or url_for('index.index'))

        cart_id = Cart.add_to_cart(current_user.id, product_id, seller_id, quantity)
        if cart_id:
            flash("Product added to cart", "success")
        else:
            flash("Failed to add product to cart", "danger")
    except Exception as e:
        print(f"Error adding to cart: {e}")
        flash("An error occurred while adding to cart", "danger")

    return redirect(request.referrer or url_for('index.index'))

@bp.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    if request.method == 'POST':
        destination_x = request.form.get('destination_x', type=int)
        destination_y = request.form.get('destination_y', type=int)
        ups_account = request.form.get('ups_account')
        warehouse_id = request.form.get('warehouse_id', type=int)
        
        if not destination_x or not destination_y:
            flash('Please provide delivery coordinates', 'danger')
            return redirect(url_for('cart.checkout'))
        
        # Find nearest warehouse if not specified
        if not warehouse_id:
            warehouse_service = WarehouseService()
            warehouse = warehouse_service.get_nearest_warehouse(destination_x, destination_y)
            if warehouse:
                warehouse_id = warehouse.warehouse_id
            else:
                flash('No warehouse available for delivery', 'danger')
                return redirect(url_for('cart.checkout'))
        
        # Process checkout
        success, result = Cart.checkout_cart(current_user.id)
        
        if success:
            # Create shipment for each order
            shipment_service = ShipmentService()
            
            for order_id in result:
                shipment_success, shipment_result = shipment_service.create_shipment(
                    order_id=order_id,
                    warehouse_id=warehouse_id,
                    destination_x=destination_x,
                    destination_y=destination_y,
                    ups_account=ups_account
                )
                
                if not shipment_success:
                    flash(f'Order placed, but shipment creation failed: {shipment_result}', 'warning')
            
            flash('Order placed successfully!', 'success')
            return redirect(url_for('amazon.order_list'))
        else:
            flash(f'Checkout failed: {result}', 'danger')
    
    # GET request
    cart_items = Cart.get_cart_items(current_user.id)
    total_cart_value = sum(item[7] for item in cart_items) if cart_items else 0
    
    # Get available warehouses
    warehouse_service = WarehouseService()
    warehouses = warehouse_service.get_all_warehouses()
    
    return render_template('checkout.html',
                          cart_items=cart_items,
                          total_cart_value=total_cart_value,
                          warehouses=warehouses)

@bp.route("/remove", methods=["POST"])
@login_required
def remove_from_cart():
    product_id = request.form.get("product_id")
    seller_id = request.form.get("seller_id")

    if not product_id or not seller_id:
        flash("Invalid removal request", "danger")
        return redirect(url_for('cart.view_cart'))

    try:
        cart_rows = app.db.execute('''
        SELECT cart_id FROM Carts 
        WHERE user_id = :user_id
        ''', user_id=current_user.id)

        if not cart_rows:
            flash("Cart not found", "danger")
            return redirect(url_for('cart.view_cart'))

        cart_id = cart_rows[0][0]

        app.db.execute('''
        DELETE FROM Cart_Products 
        WHERE cart_id = :cart_id 
        AND product_id = :product_id 
        AND seller_id = :seller_id
        ''', cart_id=cart_id, product_id=product_id, seller_id=seller_id)

        flash("Item removed from cart", "success")
    except Exception as e:
        print(f"Error removing from cart: {e}")
        flash("Error removing item", "danger")

    return redirect(url_for('cart.view_cart'))

@bp.route("/update", methods=["POST"])
@login_required
def update_cart():
    product_id = request.form.get("product_id")
    seller_id = request.form.get("seller_id")
    quantity = int(request.form.get("quantity", 1))

    if not product_id or not seller_id or quantity < 1:
        flash("Invalid update request", "danger")
        return redirect(url_for('cart.view_cart'))

    try:
        # Check availability
        inventory = Inventory.get_by_seller_and_product(seller_id, product_id)
        if not inventory or inventory.quantity < quantity:
            flash("The requested quantity is not available", "warning")
            return redirect(url_for('cart.view_cart'))

        # Get cart_id
        cart_rows = app.db.execute('''
        SELECT cart_id FROM Carts 
        WHERE user_id = :user_id
        ''', user_id=current_user.id)

        if not cart_rows:
            flash("Cart not found", "danger")
            return redirect(url_for('cart.view_cart'))

        cart_id = cart_rows[0][0]

        app.db.execute('''
        UPDATE Cart_Products
        SET quantity = :quantity
        WHERE cart_id = :cart_id
        AND product_id = :product_id
        AND seller_id = :seller_id
        ''', quantity=quantity, cart_id=cart_id, product_id=product_id, seller_id=seller_id)

        flash("Cart updated successfully", "success")
    except Exception as e:
        print(f"Error updating cart: {e}")
        flash("Error updating cart", "danger")

    return redirect(url_for('cart.view_cart'))