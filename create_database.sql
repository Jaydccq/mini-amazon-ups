-- Create database if it doesn't exist
-- Run this command from the psql prompt: CREATE DATABASE mini_amazon;
-- Then connect to the database: \c mini_amazon

-- Create tables

-- Users/Accounts table

drop table if exists accounts cascade;
drop table if exists products cascade;
drop table if exists products_categories cascade;
drop table if exists carts cascade;
drop table if exists cart_products cascade;
drop table if exists orders cascade;
drop table if exists orders_products cascade;
drop table if exists Inventory cascade;
drop table if exists warehouses cascade;
drop table if exists warehouse_products cascade;
drop table if exists shipments cascade;
drop table if exists shipment_items cascade;
drop table if exists world_messages cascade;
drop table if exists ups_messages cascade;
drop table if exists reviews cascade;
-- Drop all tables if they exist



CREATE TABLE accounts (
    user_id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    address TEXT,
    password VARCHAR(255) NOT NULL,
    current_balance NUMERIC(10, 2) DEFAULT 0.00,
    is_seller BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Product Categories
CREATE TABLE products_categories (
    category_id SERIAL PRIMARY KEY,
    category_name VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Products table
CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES products_categories(category_id),
    product_name VARCHAR(100) NOT NULL,
    description TEXT,
    image VARCHAR(255),
    price NUMERIC(10, 2) NOT NULL,
    owner_id INTEGER NOT NULL REFERENCES accounts(user_id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE Inventory (
    inventory_id SERIAL PRIMARY KEY,
    seller_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(10, 2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    owner_id INTEGER,
    warehouse_id INTEGER,
    UNIQUE (seller_id, product_id)
);

-- Carts table
CREATE TABLE carts (
    cart_id SERIAL PRIMARY KEY,
    user_id INTEGER UNIQUE NOT NULL REFERENCES accounts(user_id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Cart Products (junction table)
CREATE TABLE cart_products (
    cart_id INTEGER NOT NULL REFERENCES carts(cart_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    seller_id INTEGER NOT NULL REFERENCES accounts(user_id),
    quantity INTEGER NOT NULL DEFAULT 1,
    price_at_addition NUMERIC(10, 2) NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (cart_id, product_id, seller_id)
);

-- Orders table
CREATE TABLE orders (
    order_id SERIAL PRIMARY KEY,
    buyer_id INTEGER NOT NULL REFERENCES accounts(user_id),
    total_amount NUMERIC(10, 2) NOT NULL,
    order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    num_products INTEGER NOT NULL,
    order_status VARCHAR(20) NOT NULL DEFAULT 'Unfulfilled',
    CHECK (order_status IN ('Unfulfilled', 'Fulfilled'))
);

-- Order Products (junction table)
CREATE TABLE orders_products (
    order_item_id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(order_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity INTEGER NOT NULL,
    price NUMERIC(10, 2) NOT NULL,
    seller_id INTEGER NOT NULL REFERENCES accounts(user_id),
    status VARCHAR(20) NOT NULL DEFAULT 'Unfulfilled',
    fulfillment_date TIMESTAMP,
    UNIQUE (order_id, product_id, seller_id),
    CHECK (status IN ('Unfulfilled', 'Fulfilled'))
);

-- Warehouses table
CREATE TABLE warehouses (
    warehouse_id SERIAL PRIMARY KEY,
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    world_id BIGINT,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);



-- Warehouse Products (inventory)
CREATE TABLE warehouse_products (
    id SERIAL PRIMARY KEY,
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(warehouse_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (warehouse_id, product_id)
);

-- Shipments table
CREATE TABLE shipments (
    shipment_id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(order_id),
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(warehouse_id),
    truck_id BIGINT,
    ups_tracking_id VARCHAR(255),
    ups_account VARCHAR(255),
    destination_x INTEGER NOT NULL,
    destination_y INTEGER NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'packing',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CHECK (status IN ('packing', 'packed', 'loading', 'loaded', 'delivering', 'delivered'))
);

-- Shipment Items (products in shipment)
CREATE TABLE shipment_items (
    item_id SERIAL PRIMARY KEY,
    shipment_id INTEGER NOT NULL REFERENCES shipments(shipment_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (shipment_id, product_id)
);

-- World Messages table (for world simulator communication)
CREATE TABLE world_messages (
    id SERIAL PRIMARY KEY,
    seqnum BIGINT NOT NULL,
    message_type VARCHAR(50) NOT NULL,
    message_content TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,
    retries INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CHECK (status IN ('sent', 'acked', 'failed'))
);

-- UPS Messages table (for communication with UPS)
CREATE TABLE ups_messages (
    id SERIAL PRIMARY KEY,
    seqnum BIGINT NOT NULL,
    message_type VARCHAR(50) NOT NULL,
    message_content TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,
    retries INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CHECK (status IN ('sent', 'acked', 'failed'))
);

-- Reviews table
CREATE TABLE reviews (
    review_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES accounts(user_id),
    product_id INTEGER REFERENCES products(product_id),
    seller_id INTEGER REFERENCES accounts(user_id),
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    review_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CHECK ((product_id IS NOT NULL AND seller_id IS NULL) OR (product_id IS NULL AND seller_id IS NOT NULL))
);



-- Insert default category
INSERT INTO products_categories (category_name) VALUES ('General');

-- Insert admin user (password: 'admin')
INSERT INTO accounts (email, first_name, last_name, password, is_seller)
VALUES ('admin@example.com', 'Admin', 'User', 'pbkdf2:sha256:600000$X7oXRQ6R57gLqKzn$35de1f90a59d38c3fe36a16ae539d3bef37af183d8842fe4eaaa5661c5267bb9', TRUE);