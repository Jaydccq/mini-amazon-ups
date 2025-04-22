import logging
from sqlalchemy.exc import SQLAlchemyError
from app.model import db, Warehouse, WarehouseProduct, Product
from app.services.world_simulator_service import WorldSimulatorService

logger = logging.getLogger(__name__)

class WarehouseService:
    def __init__(self):
        self.world_simulator = WorldSimulatorService()
    
    def initialize_warehouse(self, x, y, world_id=None):
        """Initialize a new warehouse"""
        try:
            warehouse = Warehouse(
                x=x,
                y=y,
                world_id=world_id
            )
            db.session.add(warehouse)
            db.session.commit()
            
            return warehouse.warehouse_id
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Database error initializing warehouse: {str(e)}")
            return None
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error initializing warehouse: {str(e)}")
            return None
    
    def get_warehouse(self, warehouse_id):
        """Get a warehouse by ID"""
        return Warehouse.query.filter_by(warehouse_id=warehouse_id).first()
    
    def get_all_warehouses(self):
        """Get all active warehouses"""
        return Warehouse.query.filter_by(active=True).all()
    
    def get_nearest_warehouse(self, x, y):
        """Get the warehouse nearest to given coordinates"""
        return Warehouse.query.filter_by(active=True).order_by(
            (Warehouse.x - x) * (Warehouse.x - x) + 
            (Warehouse.y - y) * (Warehouse.y - y)
        ).first()
    
    def add_product_to_warehouse(self, warehouse_id, product_id, quantity):
        """Add a product to a warehouse's inventory"""
        try:
            # Check if warehouse exists
            warehouse = Warehouse.query.filter_by(warehouse_id=warehouse_id).first()
            if not warehouse:
                return False, "Warehouse not found"
            
            # Check if product exists
            product = Product.query.filter_by(product_id=product_id).first()
            if not product:
                return False, "Product not found"
            
            # Check if product already exists in warehouse
            warehouse_product = WarehouseProduct.query.filter_by(
                warehouse_id=warehouse_id,
                product_id=product_id
            ).first()
            
            if warehouse_product:
                # Update quantity
                warehouse_product.quantity += quantity
            else:
                # Create new inventory entry
                warehouse_product = WarehouseProduct(
                    warehouse_id=warehouse_id,
                    product_id=product_id,
                    quantity=quantity
                )
                db.session.add(warehouse_product)
            
            db.session.commit()
            return True, quantity
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Database error adding product to warehouse: {str(e)}")
            return False, str(e)
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error adding product to warehouse: {str(e)}")
            return False, str(e)
    
    def remove_product_from_warehouse(self, warehouse_id, product_id, quantity):
        """Remove a product from a warehouse's inventory"""
        try:
            # Check if warehouse product exists
            warehouse_product = WarehouseProduct.query.filter_by(
                warehouse_id=warehouse_id,
                product_id=product_id
            ).first()
            
            if not warehouse_product:
                return False, "Product not found in warehouse"
            
            if warehouse_product.quantity < quantity:
                return False, "Insufficient quantity available"
            
            # Update quantity
            warehouse_product.quantity -= quantity
            
            # Remove entry if quantity becomes zero
            if warehouse_product.quantity == 0:
                db.session.delete(warehouse_product)
            
            db.session.commit()
            return True, quantity
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Database error removing product from warehouse: {str(e)}")
            return False, str(e)
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error removing product from warehouse: {str(e)}")
            return False, str(e)
    
    def replenish_product(self, warehouse_id, product_id, quantity):
        """Request more of a product from the world simulator"""
        try:
            # Check if warehouse exists
            warehouse = Warehouse.query.filter_by(warehouse_id=warehouse_id).first()
            if not warehouse:
                return False, "Warehouse not found"
            
            # Check if product exists
            product = Product.query.filter_by(product_id=product_id).first()
            if not product:
                return False, "Product not found"
            
            # Request from world simulator
            success, result = self.world_simulator.buy_product(
                warehouse_id=warehouse_id,
                product_id=product_id,
                description=product.product_name,
                quantity=quantity
            )
            
            if not success:
                return False, result
            
            return True, "Replenishment requested"
        except Exception as e:
            logger.error(f"Error requesting product replenishment: {str(e)}")
            return False, str(e)
    
    def check_product_availability(self, warehouse_id, product_id, quantity_needed):
        """Check if a product is available in the specified quantity"""
        warehouse_product = WarehouseProduct.query.filter_by(
            warehouse_id=warehouse_id,
            product_id=product_id
        ).first()
        
        if not warehouse_product:
            return False
        
        return warehouse_product.quantity >= quantity_needed
    
    def get_product_inventory(self, product_id):
        """Get all warehouse inventory for a specific product"""
        inventory = WarehouseProduct.query.filter_by(
            product_id=product_id
        ).all()
        
        result = []
        for item in inventory:
            warehouse = Warehouse.query.filter_by(warehouse_id=item.warehouse_id).first()
            if warehouse:
                result.append({
                    'warehouse_id': item.warehouse_id,
                    'warehouse_location': f"({warehouse.x}, {warehouse.y})",
                    'quantity': item.quantity
                })
        
        return result
    
    def handle_product_arrived(self, warehouse_id, product_id, description, quantity):
        """Handle notification that products have arrived at the warehouse"""
        try:
            # Check if the product exists
            product = Product.query.filter_by(product_id=product_id).first()
            
            # If not, create it
            if not product:
                product = Product(
                    product_id=product_id,
                    product_name=description,
                    description=description,
                    category_id=1,  # Default category
                    owner_id=1,     # Default owner (system)
                    price=10.00     # Default price
                )
                db.session.add(product)
                db.session.flush()
            
            # Add product to warehouse inventory
            success, result = self.add_product_to_warehouse(
                warehouse_id=warehouse_id,
                product_id=product_id,
                quantity=quantity
            )
            
            if not success:
                return False, result
            
            return True, "Product added to warehouse inventory"
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error handling product arrival: {str(e)}")
            return False, str(e)
    
    def get_warehouse_inventory(self, warehouse_id):
        """Get complete inventory for a warehouse"""
        try:
            inventory = WarehouseProduct.query.filter_by(warehouse_id=warehouse_id).all()
            
            inventory_data = []
            for item in inventory:
                product = Product.query.filter_by(product_id=item.product_id).first()
                inventory_data.append({
                    'product_id': item.product_id,
                    'product_name': product.product_name if product else 'Unknown Product',
                    'quantity': item.quantity,
                    'created_at': item.created_at.isoformat() if item.created_at else None,
                    'updated_at': item.updated_at.isoformat() if item.updated_at else None
                })
            
            return inventory_data
        except Exception as e:
            logger.error(f"Error getting warehouse inventory: {str(e)}")
            return []