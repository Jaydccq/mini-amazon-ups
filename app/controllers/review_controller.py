# app/controllers/review_controller.py
from flask import render_template, Blueprint, jsonify, request, redirect, url_for, flash, current_app as app
from flask_login import current_user, login_required
from datetime import datetime
from app.models.review import ReviewService as Review
from app.models.product import ProductService
from app.models.user import UserService

bp = Blueprint('reviews', __name__, url_prefix='/reviews')

@bp.route('/')
@login_required
def user_reviews_page():
    sort_by = request.args.get('sort_by', 'date')
    sort_order = request.args.get('sort_order', 'desc')
    rating_filter = request.args.get('rating', type=int)
    recent = request.args.get('recent', type=int)

    if recent == 1:
        reviews = Review.get_recent5_by_user(current_user.id)
    else:
        reviews = Review.get_all_by_user(current_user.id)

    if rating_filter:
        reviews = [r for r in reviews if r.rating == rating_filter]

    if sort_by == 'rating':
        reviews = sorted(reviews, key=lambda r: r.rating,
                         reverse=(sort_order == 'desc'))
    else:
        reviews = sorted(reviews, key=lambda r: r.review_date,
                         reverse=(sort_order == 'desc'))

    return render_template('reviews.html',
                          reviews=reviews,
                          current_sort=sort_by,
                          current_order=sort_order,
                          current_rating=rating_filter,
                          show_recent=(recent == 1))

@bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_review():
    if request.method == 'POST':
        comment = request.form.get('comment')
        rating = int(request.form.get('rating'))
        review_type = request.form.get('review_type')

        if review_type == 'product':
            product_id = int(request.form.get('product_id'))
            seller_id = None
        else:
            product_id = None
            seller_id = int(request.form.get('seller_id'))

        try:
            success, message = Review.create_review(current_user.user_id, comment, product_id, seller_id, rating)
            if success:
                flash('Review added successfully!')
            else:
                flash(f'Error adding review: {message}', 'danger')
        except ValueError as e:
            flash(f'Error: {str(e)}')

        if product_id:
            return redirect(url_for('amazon.product_detail', product_id=product_id))
        elif seller_id:
            return redirect(url_for('reviews.user_reviews', user_id=seller_id))

    product_id = request.args.get('product_id', type=int)
    seller_id = request.args.get('seller_id', type=int)

    product = None
    seller = None

    if product_id:
        product = ProductService.get_product(product_id)
    elif seller_id:
        seller = UserService.get_user(seller_id)

    return render_template('add_review.html',
                          product=product,
                          seller=seller)

@bp.route('/edit/<int:review_id>', methods=['GET', 'POST'])
@login_required
def edit_review(review_id):
    review = Review.get(review_id)
    if not review:
        flash('Review not found!')
        return redirect(url_for('reviews.user_reviews_page'))

    if review.user_id != current_user.id:
        flash('You can only edit your own reviews!')
        return redirect(url_for('reviews.user_reviews_page'))

    if request.method == 'POST':
        comment = request.form.get('comment')
        rating = int(request.form.get('rating'))
        try:
            Review.update(review_id, comment, rating)
            flash('Review updated successfully!')
        except ValueError as e:
            flash(f'Error: {str(e)}')

        return redirect(url_for('reviews.user_reviews_page'))

    return render_template('edit_review.html', review=review)

@bp.route('/product/<int:product_id>')
def product_reviews(product_id):
    product = ProductService.get_product(product_id)
    if not product:
        flash('Product not found!')
        return redirect(url_for('amazon.index'))

    sort_by = request.args.get('sort_by', 'date')
    sort_order = request.args.get('sort_order', 'desc')

    reviews = Review.get_product_reviews(product_id)

    if sort_by == 'rating':
        reviews = sorted(reviews, key=lambda r: r.rating,
                         reverse=(sort_order == 'desc'))
    else:
        reviews = sorted(reviews, key=lambda r: r.review_date,
                         reverse=(sort_order == 'desc'))

    avg_rating, review_count = Review.get_avg_rating_product(product_id)

    rating_distribution = {star: 0 for star in range(1, 6)}
    for r in reviews:
        if r.rating in rating_distribution:
            rating_distribution[r.rating] += 1

    return render_template('product_reviews.html',
                          product=product,
                          reviews=reviews,
                          avg_rating=avg_rating,
                          review_count=review_count,
                          rating_distribution=rating_distribution,
                          current_sort=sort_by,
                          current_order=sort_order)

@bp.route('/seller/<int:seller_id>')
def seller_reviews(seller_id):
    seller = UserService.get_user(seller_id)
    if not seller:
        flash('Seller not found!')
        return redirect(url_for('amazon.index'))
        
    sort_by = request.args.get('sort_by', 'date')
    sort_order = request.args.get('sort_order', 'desc')

    reviews = Review.get_seller_reviews(seller_id)

    if sort_by == 'rating':
        reviews = sorted(reviews, key=lambda r: r.rating,
                         reverse=(sort_order == 'desc'))
    else:
        reviews = sorted(reviews, key=lambda r: r.review_date,
                         reverse=(sort_order == 'desc'))

    avg_rating, review_count = Review.get_avg_rating_seller(seller_id)
    rating_distribution = {star: 0 for star in range(1, 6)}
    for r in reviews:
        if r.rating in rating_distribution:
            rating_distribution[r.rating] += 1

    return render_template('seller_reviews.html',
                          seller=seller,
                          reviews=reviews,
                          avg_rating=avg_rating,
                          review_count=review_count,
                          rating_distribution=rating_distribution,
                          current_sort=sort_by,
                          current_order=sort_order)