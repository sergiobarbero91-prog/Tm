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
# Polígono dibujado manualmente siguiendo el trazado real de la M-30
M30_POLYGON = [
    (40.482518825255966, -3.6859700165055074),
    (40.48551209652382, -3.694132538158641),
    (40.4817272841708, -3.7051737889650838),
    (40.48009795571983, -3.713381649857041),
    (40.47582341789868, -3.721435924660682),
    (40.47327648111428, -3.7263067660209117),
    (40.472533726557515, -3.7303456294621355),
    (40.47291640327555, -3.734714103358158),
    (40.47409552637876, -3.740780731169309),
    (40.47436583195068, -3.746340540545333),
    (40.473891334487575, -3.7495678626782194),
    (40.4714648704942, -3.7509214545765985),
    (40.46786787391858, -3.749564511962177),
    (40.46390265890909, -3.7487286043740085),
    (40.4591642589443, -3.7451946521402135),
    (40.45301739243001, -3.743852777935899),
    (40.448534358361286, -3.7413314510078806),
    (40.444045118264455, -3.7393049478822604),
    (40.438020099838894, -3.737956238186257),
    (40.43417436460197, -3.7382970854690996),
    (40.42930255916818, -3.7367786983792257),
    (40.42660799625122, -3.734088413138892),
    (40.423016120233626, -3.728024069915307),
    (40.42070955979318, -3.722463028788667),
    (40.41865580249913, -3.7221267216192757),
    (40.415574900116894, -3.7233069319725587),
    (40.41275585564833, -3.723474358335295),
    (40.409937352810175, -3.7222942045227114),
    (40.40672877223773, -3.722126150510803),
    (40.402996828379514, -3.722465285404695),
    (40.40069156323037, -3.7214534554323393),
    (40.39965951423875, -3.7162298914072665),
    (40.39953416878015, -3.714376282778744),
    (40.396184823080745, -3.708644233547858),
    (40.39477395129322, -3.7042618615397203),
    (40.392720424447276, -3.7015650494093393),
    (40.383191721774836, -3.691100412790462),
    (40.38204219270969, -3.6870565130923296),
    (40.38297150905245, -3.684040180549374),
    (40.3848934221748, -3.6818466660286617),
    (40.391333800274936, -3.6776524802216386),
    (40.39404773423297, -3.673461800645754),
    (40.39854794845013, -3.6689314624247515),
    (40.40458858609219, -3.6659288994694066),
    (40.41062125145683, -3.6630956128448986),
    (40.416776113790974, -3.659091264319386),
    (40.41959062302897, -3.6587538311275694),
    (40.42676630334063, -3.6598427677226653),
    (40.432770771428665, -3.6606933334231826),
    (40.43813392726028, -3.6591938075955284),
    (40.44221386497472, -3.6592364953463914),
    (40.447064556450016, -3.6617384586054698),
    (40.454337564212295, -3.663582112997318),
    (40.45955562961302, -3.6641118995643467),
    (40.46654337429035, -3.6683392801884622),
    (40.472371494557166, -3.672562866682256),
    (40.47516166036655, -3.6742463773350664),
    (40.479348142136246, -3.6740908850299547),
    (40.481768790447006, -3.6740873995003653),
    (40.48355365642138, -3.6737494249574354),
    (40.48405844280404, -3.676094329574795),
    (40.48316450019007, -3.6806124716773923),
    (40.482518825255966, -3.6859700165055074),  # Cierre del polígono
]

def point_in_polygon(lat: float, lng: float, polygon: list) -> bool:
    """Check if a point is inside a polygon using ray casting algorithm.
    
    Polygon points are defined as (lat, lng) tuples.
    Uses the ray casting algorithm to determine if point is inside.
    """
    n = len(polygon)
    inside = False
    
    # Extract first point (lat, lng format)
    p1_lat, p1_lng = polygon[0]
    
    for i in range(1, n + 1):
        p2_lat, p2_lng = polygon[i % n]
        
        # Check if the point's latitude is within the edge's latitude range
        if lat > min(p1_lat, p2_lat):
            if lat <= max(p1_lat, p2_lat):
                if lng <= max(p1_lng, p2_lng):
                    # Calculate the x-intersection of the ray with the edge
                    if p1_lat != p2_lat:
                        lng_intersect = (lat - p1_lat) * (p2_lng - p1_lng) / (p2_lat - p1_lat) + p1_lng
                    if p1_lng == p2_lng or lng <= lng_intersect:
                        inside = not inside
        
        p1_lat, p1_lng = p2_lat, p2_lng
    
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


@router.get("/geocode/forward")
async def forward_geocode(
    address: str,
    city: str = "Madrid"
):
    """Forward geocode an address to coordinates. Public endpoint for fare calculator."""
    try:
        from geopy.geocoders import Nominatim
        
        geolocator = Nominatim(user_agent="transport_meter_app")
        
        # Add city to search if not already included
        search_address = address
        if city.lower() not in address.lower():
            search_address = f"{address}, {city}, España"
        
        location = geolocator.geocode(search_address, timeout=10)
        
        if not location:
            # Try with just the address
            location = geolocator.geocode(address, timeout=10)
        
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
        logger.error(f"Error forward geocoding: {e}")
        raise HTTPException(status_code=500, detail=f"Error al geocodificar: {str(e)}")
