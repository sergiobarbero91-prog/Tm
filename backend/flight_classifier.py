"""Commercial vs private (business/general aviation) flight classification."""
import re
from typing import Dict, Optional

PRIVATE_FLIGHT_WEIGHT = 0.25

# ICAO type codes of business jets / light turboprops
BUSINESS_AIRCRAFT_CODES = {
    "C25A", "C25B", "C25C", "C25M", "C500", "C501", "C510", "C525", "C550", "C551",
    "C560", "C56X", "C650", "C680", "C68A", "C700", "C750",
    "CL30", "CL35", "CL60", "GL5T", "GL6T", "GL7T", "GLEX",
    "GLF2", "GLF3", "GLF4", "GLF5", "GLF6", "G150", "G200", "G280", "GALX",
    "F2TH", "F900", "FA10", "FA20", "FA50", "FA6X", "FA7X", "FA8X",
    "E35L", "E50P", "E55P", "E545", "E550",
    "LJ31", "LJ35", "LJ40", "LJ45", "LJ55", "LJ60", "LJ70", "LJ75",
    "H25A", "H25B", "H25C", "BE40", "PRM1", "HDJT", "EA50", "SF50",
    "PC12", "PC24", "P180", "B350", "BE20", "BE9L", "TBM7", "TBM8", "TBM9",
}

# ICAO / IATA codes of private-aviation operators
PRIVATE_OPERATOR_CODES = {"NJE", "EJA", "VJT", "LXJ", "AHO", "JFA", "1I"}
PRIVATE_OPERATOR_KEYWORDS = (
    "netjets", "vistajet", "flexjet", "luxaviation", "air hamburg", "globeair",
    "jetfly", "gestair", "executive", "private", "privado", "jet aviation",
    "tag aviation", "air taxi", "aviación general", "aviacion general",
)

# Airline designator (2 chars IATA with at least one letter, or 3-letter ICAO) + 1-4 digits + optional suffix
_COMMERCIAL_RE = re.compile(r"^(?:(?=[A-Z0-9]{2}\d)(?:[A-Z]{2}|[A-Z]\d|\d[A-Z])|[A-Z]{3})\d{1,4}[A-Z]?$")
# Aircraft registration: prefix-suffix with hyphen, letters only (ECMKV), or N-number style (N123AB)
_REGISTRATION_RES = (
    re.compile(r"^[A-Z0-9]{1,2}-[A-Z0-9]{2,5}$"),
    re.compile(r"^[A-Z]{4,6}$"),
    re.compile(r"^N\d{1,5}[A-Z]{0,2}$"),
)


def looks_like_registration(flight_number: Optional[str]) -> bool:
    fn = (flight_number or "").strip().upper().replace(" ", "")
    if not fn or _COMMERCIAL_RE.match(fn):
        return False
    return any(r.match(fn) for r in _REGISTRATION_RES)


def is_private_flight(
    flight_number: Optional[str] = None,
    airline: Optional[str] = None,
    aircraft: Optional[str] = None,
    operator_code: Optional[str] = None,
) -> bool:
    if aircraft and aircraft.strip().upper() in BUSINESS_AIRCRAFT_CODES:
        return True
    if operator_code and operator_code.strip().upper() in PRIVATE_OPERATOR_CODES:
        return True
    name = (airline or "").lower()
    if name and any(k in name for k in PRIVATE_OPERATOR_KEYWORDS):
        return True
    return looks_like_registration(flight_number)


def flight_weight(arrival: Dict):
    """Statistical weight of an arrival: 0.25 for private flights, 1 otherwise."""
    return PRIVATE_FLIGHT_WEIGHT if arrival.get("is_private") else 1
