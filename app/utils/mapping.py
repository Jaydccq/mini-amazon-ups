# amazon-ups/app/utils/mapping.py
import logging

logger = logging.getLogger(__name__)

# Define approximate bounding box for continental US
US_BOUNDS = {
    'min_lat': 24.396308,  # South Florida
    'max_lat': 49.384358,  # Northern border
    'min_lon': -125.000000, # West Coast
    'max_lon': -66.934570   # East Coast (Maine)
}

def convert_sim_coords_to_latlon(warehouses):
    """
    Converts simulation (x, y) coordinates (0-100) to approximate
    real-world latitude and longitude within the continental US.

    Args:
        warehouses: A list of warehouse objects (or dicts) that must have
                    'warehouse_id', 'x', 'y', and 'active' attributes/keys.

    Returns:
        A list of dictionaries, each containing 'id', 'x', 'y', 'active',
        'lat', and 'lon'. Returns empty list on error.
    """
    mapped_warehouses = []
    lat_range = US_BOUNDS['max_lat'] - US_BOUNDS['min_lat']
    lon_range = US_BOUNDS['max_lon'] - US_BOUNDS['min_lon']

    if lon_range == 0 or lat_range == 0:
         logger.error("Latitude or Longitude range is zero. Check US_BOUNDS constants.")
         return []

    for wh in warehouses:
        try:
            # Validate coordinates are within expected sim range (0-100)
            sim_x = float(getattr(wh, 'x', 0)) # Use getattr for flexibility
            sim_y = float(getattr(wh, 'y', 0))
            wh_id = int(getattr(wh, 'warehouse_id', 0))
            is_active = bool(getattr(wh, 'active', False))

            # Clamp coordinates to 0-100 range before scaling
            clamped_x = max(0.0, min(100.0, sim_x))
            clamped_y = max(0.0, min(100.0, sim_y))

            # Linear scaling:
            # Map X (0-100) to Longitude (min_lon to max_lon)
            # Map Y (0-100) to Latitude (max_lat to min_lat) - Y=0 is North, Y=100 is South
            lon = US_BOUNDS['min_lon'] + (clamped_x / 100.0) * lon_range
            # Ensure lat calculation uses the defined range
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