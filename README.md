# Mini-Amazon / Mini-UPS Simulation Project

## Description

This project implements a "Mini-Amazon" online store simulation designed to interact with a "Mini-UPS" shipping system and a world simulator. It covers the workflow from user registration, product browsing, ordering, warehouse management, package packing/loading, and coordination with UPS for delivery tracking[cite: 1, 2, 93, 94].

## Features

- **User Interface (Flask Web App):**
  - User registration and login.
  - Browse a catalog of products with search and filtering.
  - Add products to a shopping cart.
  - Place orders, specifying delivery coordinates (X, Y).
  - View order history and shipment status.
  - Edit user profile.
  - Product and seller reviews.
- **Seller Features:**
  - Seller dashboard with key metrics.
  - Manage inventory listings (add/edit/delete).
  - Create new product listings.
  - View and fulfill order items.
  - Replenish stock via World Simulator.
- **Admin Features:**
  - Manage warehouses (add/view/delete).
  - Connect to and disconnect from the World Simulator.
  - View World Simulator and UPS message logs.
- **World Simulator Interaction:**
  - Connects to a simulated world via TCP using Google Protocol Buffers (GPB).
  - Manages warehouse initialization and inventory levels (buy requests).
  - Requests packing and loading of shipments.
  - Handles asynchronous responses and events (e.g., products arrived, package ready, package loaded).
  - Supports adjustable simulation speed[cite: 19].
- **UPS System Integration:**
  - Sends notifications to the UPS system (e.g., package created, loaded) via HTTP requests.
  - Receives webhook notifications from the UPS system (e.g., truck arrived, package delivered, tracking info).
  - Implements sequence number and acknowledgment mechanism for reliable communication.

## Technologies Used

- **Backend:** Python 3.12, Flask
- **Database:** PostgreSQL [cite: 146]
- **ORM:** SQLAlchemy, Flask-SQLAlchemy [cite: 146]
- **Database Migrations:** Flask-Migrate [cite: 146]
- **Authentication:** Flask-Login [cite: 146]
- **Forms & CSRF:** Flask-WTF [cite: 146]
- **API Communication:** Google Protocol Buffers (GPB), Requests
- **Containerization:** Docker, Docker Compose

## Project Structure
