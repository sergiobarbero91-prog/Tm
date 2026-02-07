"""
Geocoding router for address search and fare calculations.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import aiohttp
import logging

from shared import get_current_user_required

router = APIRouter(tags=["Geocoding"])

logger = logging.getLogger(__name__)

# M30 polygon for Madrid fare zone determination
# Detailed polygon following the actual M-30 ring road path
M30_POLYGON = [
    # North section (Plaza de Castilla area)
    (40.4658, -3.6904),  # Nudo Norte / Plaza Castilla
    (40.4689, -3.6850),  # Hacia el este
    (40.4700, -3.6780),  # Continuación norte
    
    # Northeast section (towards A-2)
    (40.4680, -3.6700),  # NE curve
    (40.4620, -3.6620),  # Hacia Ventas
    (40.4550, -3.6550),  # M-30 Este norte
    
    # East section (Ventas - O'Donnell)
    (40.4480, -3.6520),  # Ventas area
    (40.4400, -3.6500),  # Hacia O'Donnell
    (40.4320, -3.6510),  # O'Donnell
    (40.4250, -3.6530),  # Hacia Puente de Ventas
    
    # Southeast section (Moratalaz - Puente de Vallecas)
    (40.4180, -3.6560),  # Moratalaz
    (40.4100, -3.6600),  # Hacia sur
    (40.4020, -3.6680),  # Puente de Vallecas area
    (40.3950, -3.6780),  # Continuación sur
    
    # South section (Nudo Sur)
    (40.3900, -3.6900),  # Nudo Sur Este
    (40.3870, -3.7000),  # Nudo Sur
    (40.3860, -3.7100),  # Nudo Sur continuación
    (40.3870, -3.7200),  # Hacia oeste
    
    # Southwest section (Usera - Carabanchel)
    (40.3900, -3.7300),  # Usera
    (40.3950, -3.7400),  # Hacia Carabanchel
    (40.4020, -3.7480),  # Carabanchel
    
    # West section (Casa de Campo - Moncloa)
    (40.4100, -3.7520),  # Puente de Segovia area
    (40.4200, -3.7550),  # Casa de Campo
    (40.4300, -3.7560),  # Hacia Moncloa
    (40.4400, -3.7540),  # Moncloa sur
    
    # Northwest section (Moncloa - Plaza de Castilla)
    (40.4480, -3.7480),  # Moncloa
    (40.4550, -3.7380),  # Hacia norte
    (40.4600, -3.7250),  # Tetuán area
    (40.4640, -3.7100),  # Hacia Plaza Castilla
    (40.4658, -3.6980),  # Aproximación Plaza Castilla
    
    # Close polygon
    (40.4658, -3.6904),  # Volver al punto inicial
]

def point_in_polygon(lat: float, lng: float, polygon: list) -> bool:
    """Check if a point is inside a polygon using ray casting algorithm."""
    n = len(polygon)
    inside = False
    
    p1x, p1y = polygon[0]
    for i in range(1, n + 1):
        p2x, p2y = polygon[i % n]
        if lat > min(p1y, p2y):
            if lat <= max(p1y, p2y):
                if lng <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (lat - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or lng <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    
    return inside

def convert_written_numbers(text: str) -> str:
    """Convert Spanish written numbers to digits."""
    number_map = {
        'cero': '0', 'uno': '1', 'una': '1', 'dos': '2', 'tres': '3',
        'cuatro': '4', 'cinco': '5', 'seis': '6', 'siete': '7',
        'ocho': '8', 'nueve': '9', 'diez': '10', 'once': '11',
        'doce': '12', 'trece': '13', 'catorce': '14', 'quince': '15',
        'dieciséis': '16', 'dieciseis': '16', 'diecisiete': '17',
        'dieciocho': '18', 'diecinueve': '19', 'veinte': '20',
        'veintiuno': '21', 'veintidós': '22', 'veintidos': '22',
        'veintitrés': '23', 'veintitres': '23', 'veinticuatro': '24',
        'veinticinco': '25', 'treinta': '30', 'cuarenta': '40',
        'cincuenta': '50', 'sesenta': '60', 'setenta': '70',
        'ochenta': '80', 'noventa': '90', 'cien': '100'
    }
    
    result = text.lower()
    for word, digit in number_map.items():
        result = result.replace(word, digit)
    
    return result


# Models
class GeocodeAddressRequest(BaseModel):
    address: str
    city: str = "Madrid"

class SearchAddressRequest(BaseModel):
    query: str
    city: str = "Madrid"

class ReverseGeocodeRequest(BaseModel):
    latitude: float
    longitude: float


@router.post("/geocode-address")
async def geocode_address(
    request: GeocodeAddressRequest,
    current_user: dict = Depends(get_current_user_required)
):
    """Geocode an address and determine if it's inside the M30."""
    try:
        from geopy.geocoders import Nominatim
        
        geolocator = Nominatim(user_agent="commute-pulse-app")
        
        # Add city to search if not already included
        search_address = request.address
        if request.city.lower() not in request.address.lower():
            search_address = f"{request.address}, {request.city}, España"
        
        location = geolocator.geocode(search_address)
        
        if not location:
            # Try with just the address
            location = geolocator.geocode(request.address)
        
        if not location:
            raise HTTPException(status_code=404, detail="No se encontró la dirección")
        
        lat = location.latitude
        lng = location.longitude
        
        # Check if inside M30
        is_inside_m30 = point_in_polygon(lat, lng, M30_POLYGON)
        
        return {
            "address": location.address,
            "latitude": lat,
            "longitude": lng,
            "is_inside_m30": is_inside_m30
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error geocoding address: {e}")
        raise HTTPException(status_code=500, detail=f"Error al geocodificar: {str(e)}")


@router.post("/search-addresses")
async def search_addresses(
    request: SearchAddressRequest,
    current_user: dict = Depends(get_current_user_required)
):
    """Search for addresses using Photon API (faster than Nominatim) with fallback."""
    try:
        # First, convert any written numbers to digits
        query = convert_written_numbers(request.query)
        
        # Add Madrid context if not present
        if "madrid" not in query.lower():
            search_query = f"{query}, Madrid"
        else:
            search_query = query
        
        suggestions = []
        
        # Try Photon API first (faster, better autocomplete)
        try:
            async with aiohttp.ClientSession() as session:
                # Photon API - fast geocoding powered by OpenStreetMap
                photon_url = "https://photon.komoot.io/api/"
                params = {
                    "q": search_query,
                    "limit": 7,
                    "lat": 40.4168,  # Madrid center for better local results
                    "lon": -3.7038,
                    "location_bias_scale": 0.5  # Prefer results near Madrid
                }
                
                async with session.get(photon_url, params=params, timeout=3) as response:
                    if response.status == 200:
                        data = await response.json()
                        features = data.get("features", [])
                        
                        for feature in features:
                            props = feature.get("properties", {})
                            geom = feature.get("geometry", {})
                            coords = geom.get("coordinates", [])
                            
                            if len(coords) >= 2:
                                lng, lat = coords[0], coords[1]
                                
                                # Build address string
                                parts = []
                                if props.get("street"):
                                    street = props["street"]
                                    if props.get("housenumber"):
                                        street = f"{street} {props['housenumber']}"
                                    parts.append(street)
                                elif props.get("name"):
                                    parts.append(props["name"])
                                
                                if props.get("city") or props.get("locality"):
                                    parts.append(props.get("city") or props.get("locality"))
                                
                                if not parts:
                                    continue
                                
                                address = ", ".join(parts)
                                
                                # Check if inside M30
                                is_inside_m30 = point_in_polygon(lat, lng, M30_POLYGON)
                                
                                suggestions.append({
                                    "address": address,
                                    "latitude": lat,
                                    "longitude": lng,
                                    "is_inside_m30": is_inside_m30
                                })
                        
                        if suggestions:
                            logger.info(f"Photon found {len(suggestions)} results for '{query}'")
                            return {"suggestions": suggestions[:5]}
        
        except Exception as photon_error:
            logger.warning(f"Photon API failed: {photon_error}, falling back to Nominatim")
        
        # Fallback to Nominatim if Photon fails
        from geopy.geocoders import Nominatim
        
        geolocator = Nominatim(user_agent="commute-pulse-app-v2", timeout=5)
        
        locations = geolocator.geocode(
            f"{search_query}, España", 
            exactly_one=False, 
            limit=5,
            addressdetails=True
        )
        
        if locations:
            for loc in locations:
                lat = loc.latitude
                lng = loc.longitude
                is_inside_m30 = point_in_polygon(lat, lng, M30_POLYGON)
                
                suggestions.append({
                    "address": loc.address,
                    "latitude": lat,
                    "longitude": lng,
                    "is_inside_m30": is_inside_m30
                })
        
        return {"suggestions": suggestions}
        
    except Exception as e:
        logger.error(f"Error searching addresses: {e}")
        return {"suggestions": []}


@router.get("/geocode/reverse")
async def reverse_geocode(
    lat: float,
    lng: float,
    current_user: dict = Depends(get_current_user_required)
):
    """Reverse geocode coordinates to get street name."""
    try:
        from geopy.geocoders import Nominatim
        
        geolocator = Nominatim(user_agent="transport_meter_app")
        location = geolocator.reverse(f"{lat}, {lng}", language="es")
        
        if not location:
            return {"street_name": "Ubicación desconocida", "full_address": None}
        
        address = location.raw.get('address', {})
        
        # Try to get the most specific street name
        street = (
            address.get('road') or 
            address.get('pedestrian') or 
            address.get('neighbourhood') or
            address.get('suburb') or
            "Ubicación desconocida"
        )
        
        # Check if inside M30
        is_inside_m30 = point_in_polygon(lat, lng, M30_POLYGON)
        
        return {
            "street_name": street,
            "full_address": location.address,
            "is_inside_m30": is_inside_m30
        }
    except Exception as e:
        logger.error(f"Error reverse geocoding: {e}")
        return {"street_name": "Error de geocodificación", "full_address": None}
