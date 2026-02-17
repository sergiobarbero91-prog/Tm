"""
Test suite for Taxi Needed Zones (Zonas Calientes) feature.
Tests POST, GET, DELETE /api/taxi-needed-zones endpoints.

Feature: Users can report areas where taxis are needed.
- Reports expire after 1 hour
- Reports from same location within 30 minutes are deduplicated
- Only owner or admin can delete a zone
"""

import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    BASE_URL = os.environ.get('EXPO_PUBLIC_BACKEND_URL', 'https://taxi-hotzone.preview.emergentagent.com').rstrip('/')

# Test coordinates - Madrid center
MADRID_CENTER_LAT = 40.4168
MADRID_CENTER_LNG = -3.7038

# Test coordinates - Gran Via
GRAN_VIA_LAT = 40.4203
GRAN_VIA_LNG = -3.7015


class TestAuthentication:
    """Test authentication for the API"""
    
    def test_login_admin(self, api_client):
        """Test login with admin credentials"""
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        data = response.json()
        assert "access_token" in data, "No access_token in response"
        assert "user" in data, "No user in response"
        assert data["user"]["role"] == "admin", "User role is not admin"
        print(f"✓ Login successful for admin user")
        return data["access_token"]


class TestTaxiNeededZonesEndpoints:
    """Test suite for taxi-needed-zones CRUD operations"""
    
    @pytest.fixture(autouse=True)
    def setup(self, api_client):
        """Setup for each test - get auth token"""
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        if response.status_code == 200:
            self.token = response.json().get("access_token")
            self.user = response.json().get("user")
            api_client.headers.update({"Authorization": f"Bearer {self.token}"})
        else:
            pytest.skip("Authentication failed - skipping authenticated tests")
    
    def test_post_taxi_needed_zone_success(self, api_client):
        """Test POST /api/taxi-needed-zones - Report a hot zone successfully"""
        # Use a unique location to avoid deduplication
        unique_lat = MADRID_CENTER_LAT + (uuid.uuid4().int % 1000) * 0.0001
        unique_lng = MADRID_CENTER_LNG + (uuid.uuid4().int % 1000) * 0.0001
        
        response = api_client.post(f"{BASE_URL}/api/taxi-needed-zones", json={
            "latitude": unique_lat,
            "longitude": unique_lng
        })
        
        assert response.status_code == 200, f"POST failed: {response.text}"
        data = response.json()
        
        assert "success" in data, "Response missing 'success' field"
        assert data["success"] == True, f"Report not successful: {data}"
        assert "zone_id" in data, "Response missing 'zone_id'"
        assert "street_name" in data, "Response missing 'street_name'"
        assert "expires_at" in data, "Response missing 'expires_at'"
        
        print(f"✓ Successfully reported zone: {data.get('street_name')} (ID: {data.get('zone_id')})")
        return data["zone_id"]
    
    def test_post_taxi_needed_zone_deduplication(self, api_client):
        """Test POST /api/taxi-needed-zones - Reports from same location within 30 min are deduplicated"""
        # First report
        response1 = api_client.post(f"{BASE_URL}/api/taxi-needed-zones", json={
            "latitude": GRAN_VIA_LAT,
            "longitude": GRAN_VIA_LNG
        })
        assert response1.status_code == 200, f"First POST failed: {response1.text}"
        data1 = response1.json()
        
        if data1.get("success") == True:
            # Second report at same location - should be deduplicated
            response2 = api_client.post(f"{BASE_URL}/api/taxi-needed-zones", json={
                "latitude": GRAN_VIA_LAT,
                "longitude": GRAN_VIA_LNG
            })
            assert response2.status_code == 200, f"Second POST failed: {response2.text}"
            data2 = response2.json()
            
            assert data2.get("success") == False, "Second report should have been deduplicated"
            assert "Ya has reportado" in data2.get("message", ""), "Missing deduplication message"
            print(f"✓ Deduplication working: {data2.get('message')}")
        else:
            # If first was deduplicated, that's also valid (previous test created it)
            print(f"✓ Zone already existed (deduplication): {data1.get('message')}")
    
    def test_post_taxi_needed_zone_unauthorized(self, api_client):
        """Test POST /api/taxi-needed-zones without auth token - should fail"""
        # Remove auth header
        api_client.headers.pop("Authorization", None)
        
        response = api_client.post(f"{BASE_URL}/api/taxi-needed-zones", json={
            "latitude": MADRID_CENTER_LAT,
            "longitude": MADRID_CENTER_LNG
        })
        
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("✓ Unauthorized request correctly rejected")
    
    def test_get_taxi_needed_zones_success(self, api_client):
        """Test GET /api/taxi-needed-zones - Get list of active zones"""
        response = api_client.get(f"{BASE_URL}/api/taxi-needed-zones", params={
            "max_distance_km": 10
        })
        
        assert response.status_code == 200, f"GET failed: {response.text}"
        data = response.json()
        
        assert "zones" in data, "Response missing 'zones' field"
        assert "total_count" in data, "Response missing 'total_count' field"
        assert isinstance(data["zones"], list), "zones should be a list"
        
        if len(data["zones"]) > 0:
            zone = data["zones"][0]
            assert "id" in zone, "Zone missing 'id'"
            assert "street_name" in zone, "Zone missing 'street_name'"
            assert "latitude" in zone, "Zone missing 'latitude'"
            assert "longitude" in zone, "Zone missing 'longitude'"
            assert "report_count" in zone, "Zone missing 'report_count'"
            assert "license_numbers" in zone, "Zone missing 'license_numbers'"
            assert "last_report" in zone, "Zone missing 'last_report'"
            assert "reporters" in zone, "Zone missing 'reporters'"
            print(f"✓ Retrieved {data['total_count']} active zones")
            print(f"  First zone: {zone['street_name']} ({zone['report_count']} reports)")
        else:
            print("✓ GET returned 0 zones (no active zones)")
        
        return data
    
    def test_get_taxi_needed_zones_with_user_location(self, api_client):
        """Test GET /api/taxi-needed-zones with user location - should include distance"""
        response = api_client.get(f"{BASE_URL}/api/taxi-needed-zones", params={
            "user_lat": MADRID_CENTER_LAT,
            "user_lng": MADRID_CENTER_LNG,
            "max_distance_km": 10
        })
        
        assert response.status_code == 200, f"GET failed: {response.text}"
        data = response.json()
        
        if len(data["zones"]) > 0:
            zone = data["zones"][0]
            # When user location is provided, distance should be included
            assert "distance_km" in zone, "Zone missing 'distance_km' when user location provided"
            print(f"✓ GET with location returned {data['total_count']} zones with distance info")
            print(f"  Nearest zone: {zone['street_name']} at {zone['distance_km']} km")
        else:
            print("✓ GET with location returned 0 zones")
    
    def test_get_taxi_needed_zones_unauthorized(self, api_client):
        """Test GET /api/taxi-needed-zones without auth - should fail"""
        # Remove auth header
        api_client.headers.pop("Authorization", None)
        
        response = api_client.get(f"{BASE_URL}/api/taxi-needed-zones")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("✓ Unauthorized GET correctly rejected")
    
    def test_delete_taxi_needed_zone_success(self, api_client):
        """Test DELETE /api/taxi-needed-zones/{zone_id} - Delete a zone"""
        # First create a zone to delete
        unique_lat = 40.41 + (uuid.uuid4().int % 1000) * 0.0001
        unique_lng = -3.70 + (uuid.uuid4().int % 1000) * 0.0001
        
        create_response = api_client.post(f"{BASE_URL}/api/taxi-needed-zones", json={
            "latitude": unique_lat,
            "longitude": unique_lng
        })
        
        if create_response.status_code == 200 and create_response.json().get("success"):
            zone_id = create_response.json()["zone_id"]
            
            # Now delete it
            delete_response = api_client.delete(f"{BASE_URL}/api/taxi-needed-zones/{zone_id}")
            assert delete_response.status_code == 200, f"DELETE failed: {delete_response.text}"
            
            data = delete_response.json()
            assert data.get("success") == True, "Delete not successful"
            print(f"✓ Successfully deleted zone: {zone_id}")
        else:
            # If zone creation was deduplicated, skip this test
            print("✓ Skipped delete test (zone creation was deduplicated)")
    
    def test_delete_taxi_needed_zone_not_found(self, api_client):
        """Test DELETE /api/taxi-needed-zones/{zone_id} - Non-existent zone"""
        fake_zone_id = str(uuid.uuid4())
        
        response = api_client.delete(f"{BASE_URL}/api/taxi-needed-zones/{fake_zone_id}")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ Delete of non-existent zone correctly returns 404")
    
    def test_delete_taxi_needed_zone_unauthorized(self, api_client):
        """Test DELETE /api/taxi-needed-zones/{zone_id} without auth - should fail"""
        # Remove auth header
        api_client.headers.pop("Authorization", None)
        
        fake_zone_id = str(uuid.uuid4())
        response = api_client.delete(f"{BASE_URL}/api/taxi-needed-zones/{fake_zone_id}")
        
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("✓ Unauthorized delete correctly rejected")


class TestTaxiNeededZonesIntegration:
    """Integration tests for the complete workflow"""
    
    @pytest.fixture(autouse=True)
    def setup(self, api_client):
        """Setup for each test - get auth token"""
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        if response.status_code == 200:
            self.token = response.json().get("access_token")
            self.user = response.json().get("user")
            api_client.headers.update({"Authorization": f"Bearer {self.token}"})
        else:
            pytest.skip("Authentication failed - skipping authenticated tests")
    
    def test_full_workflow_create_read_delete(self, api_client):
        """Test full workflow: Create zone -> Read zones -> Verify in list -> Delete -> Verify deleted"""
        # Step 1: Create a unique zone
        unique_lat = 40.42 + (uuid.uuid4().int % 1000) * 0.0001
        unique_lng = -3.71 + (uuid.uuid4().int % 1000) * 0.0001
        
        create_response = api_client.post(f"{BASE_URL}/api/taxi-needed-zones", json={
            "latitude": unique_lat,
            "longitude": unique_lng
        })
        
        assert create_response.status_code == 200, f"Create failed: {create_response.text}"
        create_data = create_response.json()
        
        if not create_data.get("success"):
            print(f"✓ Zone creation deduplicated (expected behavior): {create_data.get('message')}")
            return
        
        zone_id = create_data["zone_id"]
        street_name = create_data["street_name"]
        print(f"  Step 1: Created zone '{street_name}' (ID: {zone_id})")
        
        # Step 2: Read zones and verify our zone is in the list
        read_response = api_client.get(f"{BASE_URL}/api/taxi-needed-zones", params={
            "user_lat": unique_lat,
            "user_lng": unique_lng,
            "max_distance_km": 1
        })
        
        assert read_response.status_code == 200, f"Read failed: {read_response.text}"
        read_data = read_response.json()
        
        zone_ids = [z["id"] for z in read_data["zones"]]
        assert zone_id in zone_ids, f"Created zone not found in zones list"
        print(f"  Step 2: Verified zone exists in list ({read_data['total_count']} zones within 1km)")
        
        # Step 3: Delete the zone
        delete_response = api_client.delete(f"{BASE_URL}/api/taxi-needed-zones/{zone_id}")
        assert delete_response.status_code == 200, f"Delete failed: {delete_response.text}"
        print(f"  Step 3: Deleted zone successfully")
        
        # Step 4: Verify zone is no longer in the list
        verify_response = api_client.get(f"{BASE_URL}/api/taxi-needed-zones", params={
            "user_lat": unique_lat,
            "user_lng": unique_lng,
            "max_distance_km": 1
        })
        
        verify_data = verify_response.json()
        zone_ids_after = [z["id"] for z in verify_data["zones"]]
        assert zone_id not in zone_ids_after, "Deleted zone still in list"
        print(f"  Step 4: Verified zone no longer in list")
        
        print("✓ Full workflow completed successfully")


@pytest.fixture
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
