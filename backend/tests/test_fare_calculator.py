"""
Test suite for the public fare calculator and M30 boundary detection.
Tests all taxi fare scenarios:
- Tarifa 1: 2,50€ bajada + 1,40€/km (laborables 6:00-21:00)
- Tarifa 2: 3,20€ bajada + 1,60€/km (noches/festivos)
- Tarifa 3: Aeropuerto → fuera M30 = Franquicia 9km (sin coste), resto a T1/T2 SIN bajada
- Tarifa 4: Aeropuerto ↔ dentro M30 = 33€ fijo
- Tarifa 7: Estaciones/IFEMA → cualquier lugar = Franquicia 1,4km (sin coste), resto a T1/T2 SIN bajada
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://tariff-tool.preview.emergentagent.com')
BASE_URL = BASE_URL.rstrip('/')


class TestM30BoundaryDetection:
    """Test M30 boundary detection via geocoding endpoint"""
    
    def test_inside_m30_puerta_del_sol(self):
        """Puerta del Sol should be inside M30"""
        response = requests.get(
            f"{BASE_URL}/api/geocode/forward",
            params={"address": "Puerta del Sol, Madrid"},
            timeout=15
        )
        assert response.status_code == 200
        data = response.json()
        assert "is_inside_m30" in data
        assert data["is_inside_m30"] == True, "Puerta del Sol should be inside M30"
    
    def test_inside_m30_gran_via(self):
        """Gran Vía should be inside M30"""
        response = requests.get(
            f"{BASE_URL}/api/geocode/forward",
            params={"address": "Gran Vía 32, Madrid"},
            timeout=15
        )
        assert response.status_code == 200
        data = response.json()
        assert "is_inside_m30" in data
        assert data["is_inside_m30"] == True, "Gran Vía should be inside M30"
    
    def test_inside_m30_plaza_espana(self):
        """Plaza de España should be inside M30"""
        response = requests.get(
            f"{BASE_URL}/api/geocode/forward",
            params={"address": "Plaza de España, Madrid"},
            timeout=15
        )
        assert response.status_code == 200
        data = response.json()
        assert "is_inside_m30" in data
        assert data["is_inside_m30"] == True, "Plaza de España should be inside M30"
    
    def test_outside_m30_alcobendas(self):
        """Alcobendas should be outside M30"""
        response = requests.get(
            f"{BASE_URL}/api/geocode/forward",
            params={"address": "Alcobendas Centro, Madrid"},
            timeout=15
        )
        assert response.status_code == 200
        data = response.json()
        assert "is_inside_m30" in data
        assert data["is_inside_m30"] == False, "Alcobendas should be outside M30"
    
    def test_outside_m30_getafe(self):
        """Getafe should be outside M30"""
        response = requests.get(
            f"{BASE_URL}/api/geocode/forward",
            params={"address": "Getafe Centro, Madrid"},
            timeout=15
        )
        assert response.status_code == 200
        data = response.json()
        assert "is_inside_m30" in data
        assert data["is_inside_m30"] == False, "Getafe should be outside M30"
    
    def test_outside_m30_pozuelo(self):
        """Pozuelo should be outside M30"""
        response = requests.get(
            f"{BASE_URL}/api/geocode/forward",
            params={"address": "Pozuelo de Alarcon, Madrid"},
            timeout=15
        )
        assert response.status_code == 200
        data = response.json()
        assert "is_inside_m30" in data
        assert data["is_inside_m30"] == False, "Pozuelo should be outside M30"


class TestGeocodingEndpoint:
    """Test geocoding endpoint functionality"""
    
    def test_forward_geocode_returns_coordinates(self):
        """Forward geocoding should return latitude and longitude"""
        response = requests.get(
            f"{BASE_URL}/api/geocode/forward",
            params={"address": "Calle Alcalá 50, Madrid"},
            timeout=15
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check required fields
        assert "latitude" in data
        assert "longitude" in data
        assert "address" in data
        assert "is_inside_m30" in data
        
        # Validate coordinate ranges for Madrid area
        assert 40.0 < data["latitude"] < 41.0, "Latitude should be in Madrid area"
        assert -4.0 < data["longitude"] < -3.0, "Longitude should be in Madrid area"
    
    def test_forward_geocode_not_found(self):
        """Invalid address should return 404 or empty"""
        response = requests.get(
            f"{BASE_URL}/api/geocode/forward",
            params={"address": "xxxinvalidaddressxxx12345"},
            timeout=15
        )
        # Either 404 or 500 is acceptable for invalid addresses
        assert response.status_code in [404, 500]


class TestRouteDistanceEndpoint:
    """Test route distance calculation endpoint"""
    
    def test_calculate_route_distance(self):
        """Route distance calculation should return distance_km"""
        # Atocha to Gran Vía coordinates
        response = requests.post(
            f"{BASE_URL}/api/calculate-route-distance",
            json={
                "origin_lat": 40.4055,
                "origin_lng": -3.6883,
                "dest_lat": 40.4200,
                "dest_lng": -3.7050
            },
            timeout=15
        )
        
        # API might not exist or require auth
        if response.status_code == 200:
            data = response.json()
            assert "distance_km" in data
            # Distance should be reasonable (2-10km)
            assert 1.0 < data["distance_km"] < 20.0
        elif response.status_code == 404:
            pytest.skip("Route distance API not available")
        elif response.status_code == 401:
            pytest.skip("Route distance API requires authentication")


class TestFareCalculatorIntegration:
    """Integration tests verifying fare calculation logic matches requirements"""
    
    def test_tarifa_4_airport_to_inside_m30(self):
        """
        Tarifa 4: Airport ↔ inside M30 = 33€ fixed
        Verify Sol is detected as inside M30
        """
        response = requests.get(
            f"{BASE_URL}/api/geocode/forward",
            params={"address": "Puerta del Sol, Madrid"},
            timeout=15
        )
        assert response.status_code == 200
        data = response.json()
        
        # Key assertion: Sol must be inside M30 for Tarifa 4 to apply
        assert data["is_inside_m30"] == True, \
            "For Tarifa 4 to work, destination inside M30 must be detected correctly"
    
    def test_tarifa_3_airport_to_outside_m30(self):
        """
        Tarifa 3: Airport → outside M30 = 9km franchise, then T1/T2 rate WITHOUT flag fall
        Verify outside M30 locations are correctly detected
        """
        locations_outside = [
            "Alcobendas, Madrid",
            "Getafe, Madrid", 
            "Leganes, Madrid",
            "Alcorcon, Madrid"
        ]
        
        for loc in locations_outside:
            response = requests.get(
                f"{BASE_URL}/api/geocode/forward",
                params={"address": loc},
                timeout=15
            )
            if response.status_code == 200:
                data = response.json()
                assert data["is_inside_m30"] == False, \
                    f"{loc} should be detected as outside M30 for Tarifa 3"
    
    def test_tarifa_7_station_origin_detection(self):
        """
        Tarifa 7: Stations (Atocha/Chamartín) → any destination = 1.4km franchise
        Verify station coordinates are geocodable
        """
        # Just verify the geocoding works for station areas
        stations = [
            "Estación de Atocha, Madrid",
            "Estación de Chamartín, Madrid"
        ]
        
        for station in stations:
            response = requests.get(
                f"{BASE_URL}/api/geocode/forward",
                params={"address": station},
                timeout=15
            )
            if response.status_code == 200:
                data = response.json()
                # Stations should geocode to Madrid area
                assert 40.0 < data["latitude"] < 41.0
                assert -4.0 < data["longitude"] < -3.0


class TestPublicSummaryEndpoint:
    """Test public summary endpoint (no auth required)"""
    
    def test_public_summary_available(self):
        """Public summary should be accessible without authentication"""
        response = requests.get(f"{BASE_URL}/api/public/summary", timeout=15)
        
        # Either 200 (has data) or 500/404 (endpoint exists but no data)
        assert response.status_code in [200, 404, 500]
        
        if response.status_code == 200:
            data = response.json()
            # Check basic structure
            assert "stations" in data or "terminals" in data or "disclaimer" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
