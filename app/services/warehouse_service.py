import logging
from sqlalchemy.exc import SQLAlchemyError
from app.model import db, Warehouse, WarehouseProduct, Product
from app.services.world_simulator_service import WorldSimulatorService

logger = logging.getLogger(__name__)
from flask import current_app
class WarehouseService:
    def __init__(self):
        # self.world_simulator = current_app.config.get('WORLD_SIMULATOR_SERVICE')
        self.world_simulator = current_app.config.get('WORLD_SIMULATOR_SERVICE') 
    
    def initialize_warehouse(self, x, y, world_id=None):
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
    #get a warehouse by ID
    def get_warehouse(self, warehouse_id):
        return Warehouse.query.filter_by(warehouse_id=warehouse_id).first()
    
    #get all active warehouses
    def get_all_warehouses(self):
        return Warehouse.query.filter_by(active=True).all()
    
    #get all warehouses by distance
    def get_nearest_warehouse(self, x, y):
        return Warehouse.query.filter_by(active=True).order_by(
            (Warehouse.x - x) * (Warehouse.x - x) + 
            (Warehouse.y - y) * (Warehouse.y - y)
        ).first()
    
    # add a product to a warehouse
    def add_product_to_warehouse(self, warehouse_id, product_id, quantity):
        try:
            warehouse = Warehouse.query.filter_by(warehouse_id=warehouse_id).first()
            if not warehouse:
                return False, "Warehouse not found"
            
            product = Product.query.filter_by(product_id=product_id).first()
            if not product:
                return False, "Product not found"
            
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
    
    # remove a product from a warehouse
    def remove_product_from_warehouse(self, warehouse_id, product_id, quantity):
        try:
            warehouse_product = WarehouseProduct.query.filter_by(
                warehouse_id=warehouse_id,
                product_id=product_id
            ).first()
            
            if not warehouse_product:
                return False, "Product not found in warehouse"
            
            if warehouse_product.quantity < quantity:
                return False, "Insufficient quantity available"
            
            warehouse_product.quantity -= quantity
            
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
    
    # replenish a product from the world simulator
    def replenish_product(self, warehouse_id, product_id, quantity):
        if not self.world_simulator or not self.world_simulator.connected:
             logger.warning("WarehouseService: Attempted replenish_product but world_simulator is not connected.")
             return False, "Not connected to World Simulator"
        try:
            warehouse = Warehouse.query.filter_by(warehouse_id=warehouse_id).first()
            if not warehouse:
                return False, "Warehouse not found"
            
            product = Product.query.filter_by(product_id=product_id).first()
            if not product:
                return False, "Product not found"
            
            success, result = self.world_simulator.buy_product(
                warehouse_id=warehouse_id,
                product_id=product_id,
                description=product.product_name,
                quantity=quantity
            )
            
            if not success:
                logger.error(f"World sim buy_product failed for WH:{warehouse_id}, Prod:{product_id}. Result: {result}")

                return False, result
            logger.info(f"Replenishment request successful for WH:{warehouse_id}, Prod:{product_id}. Result: {result}")
            return True, "Replenishment requested"
        except Exception as e:
            logger.error(f"Error requesting product replenishment: {str(e)}")
            return False, str(e)
    
    # check if a product is available in a warehouse
    def check_product_availability(self, warehouse_id, product_id, quantity_needed):
        warehouse_product = WarehouseProduct.query.filter_by(
            warehouse_id=warehouse_id,
            product_id=product_id
        ).first()
        
        if not warehouse_product:
            return False
        
        return warehouse_product.quantity >= quantity_needed
    
    def get_product_inventory(self, product_id):

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
        try:
            product = Product.query.filter_by(product_id=product_id).first()
            
            # If not, create it
            if not product:
                product = Product(
                    product_id=product_id,
                    product_name=description,
                    description=description,
                    category_id=1,  
                    owner_id=1,     
                    price=10.00     # Default price？？？
                )
                db.session.add(product)
                db.session.flush()
            
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
        
    from datetime import datetime
    def add_product_to_warehouse(self, warehouse_id, product_id, quantity):
        try:
            # Ensure warehouse and product exist (important!)
            warehouse = Warehouse.query.get(warehouse_id)
            if not warehouse:
                return False, f"Warehouse ID {warehouse_id} not found."
            # Ensure product exists (important!)
            product = Product.query.get(product_id)
            if not product:
                return False, f"Product ID {product_id} not found."

            # Find existing warehouse-product link
            warehouse_product = WarehouseProduct.query.filter_by(
                warehouse_id=warehouse_id,
                product_id=product_id
            ).first()

            if warehouse_product:
                # Update quantity if record exists
                warehouse_product.quantity += quantity
                warehouse_product.updated_at = datetime.utcnow() # Manually update timestamp
                # print(f"Updating WHP: WH={warehouse_id}, Prod={product_id}, New Qty={warehouse_product.quantity}")
            else:
                # Create new inventory entry if it doesn't exist
                warehouse_product = WarehouseProduct(
                    warehouse_id=warehouse_id,
                    product_id=product_id,
                    quantity=quantity
                )
                # print(f"Creating WHP: WH={warehouse_id}, Prod={product_id}, Qty={quantity}")
                db.session.add(warehouse_product)

            db.session.commit()
            return True, warehouse_product.quantity # Return the new total quantity
        except SQLAlchemyError as e:
            db.session.rollback()
            # Log the error properly in a real application
            logger.error(f"Database error adding product {product_id} to warehouse {warehouse_id}: {str(e)}")
            return False, f"Database error: {str(e)}"
        except Exception as e:
            db.session.rollback()
            # Log the error properly in a real application
            logger.error(f"Error adding product {product_id} to warehouse {warehouse_id}: {str(e)}")
            return False, f"Error: {str(e)}"