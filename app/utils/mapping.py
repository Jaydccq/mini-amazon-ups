# amazon-ups/app/utils/mapping.py
import logging

logger = logging.getLogger(__name__)

US_BOUNDS = {
    'min_lat': 30.396308,  #
    'max_lat': 47.384358,  
    'min_lon': -125.000000, 
    'max_lon': -81.934570   
}

def convert_sim_coords_to_latlon(warehouses):

    mapped_warehouses = []
    lat_range = US_BOUNDS['max_lat'] - US_BOUNDS['min_lat']
    lon_range = US_BOUNDS['max_lon'] - US_BOUNDS['min_lon']

    if lon_range == 0 or lat_range == 0:
         logger.error("Latitude or Longitude range is zero. Check US_BOUNDS constants.")
         return []

    for wh in warehouses:
        try:
            sim_x = float(getattr(wh, 'x', 0)) # Use getattr for flexibility
            sim_y = float(getattr(wh, 'y', 0))
            wh_id = int(getattr(wh, 'warehouse_id', 0))
            is_active = bool(getattr(wh, 'active', False))

            clamped_x = max(0.0, min(100.0, sim_x))
            clamped_y = max(0.0, min(100.0, sim_y))

            lon = US_BOUNDS['min_lon'] + (clamped_x / 100.0) * lon_range
            lat = US_BOUNDS['max_lat'] - (clamped_y / 100.0) * lat_range

            mapped_warehouses.append({
                'id': wh_id,
                'x': sim_x, # Store original sim coords
                'y': sim_y,
                'active': is_active,
                'lat': lat,
                'lon': lon
            })
        except (TypeError, ValueError, AttributeError) as e:
            wh_identifier = getattr(wh, 'warehouse_id', 'Unknown ID')
            logger.warning(f"Could not convert coordinates for warehouse {wh_identifier}: {e}")
            continue # Skip this warehouse if coordinates are invalid

    return mapped_warehouses