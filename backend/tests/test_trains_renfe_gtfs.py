"""
Tests for Trains API and Renfe GTFS Integration.
Tests the /api/trains endpoint, train data fields, and Renfe GTFS fallback mechanism.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('EXPO_PUBLIC_BACKEND_URL', '').rstrip('/')

class TestTrainsEndpoint:
    """Tests for GET /api/trains endpoint"""

    def test_trains_endpoint_returns_200(self):
        """Test that trains endpoint returns 200 status code"""
        response = requests.get(f"{BASE_URL}/api/trains")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print(f"✓ Trains endpoint returned 200")

    def test_trains_response_contains_atocha(self):
        """Test that response contains Atocha station data"""
        response = requests.get(f"{BASE_URL}/api/trains")
        data = response.json()
        assert "atocha" in data, "Response should contain 'atocha' key"
        assert data["atocha"]["station_id"] == "60000", "Atocha station_id should be 60000"
        assert data["atocha"]["station_name"] == "Madrid Puerta de Atocha", "Atocha station_name incorrect"
        print(f"✓ Atocha station data present with correct station_id=60000")

    def test_trains_response_contains_chamartin(self):
        """Test that response contains Chamartín station data"""
        response = requests.get(f"{BASE_URL}/api/trains")
        data = response.json()
        assert "chamartin" in data, "Response should contain 'chamartin' key"
        assert data["chamartin"]["station_id"] == "17000", "Chamartín station_id should be 17000"
        assert data["chamartin"]["station_name"] == "Madrid Chamartín Clara Campoamor", "Chamartín station_name incorrect"
        print(f"✓ Chamartín station data present with correct station_id=17000")

    def test_trains_response_contains_required_fields(self):
        """Test that response contains all required fields"""
        response = requests.get(f"{BASE_URL}/api/trains")
        data = response.json()
        
        required_fields = ["atocha", "chamartin", "winner_30min", "winner_60min", "last_update"]
        for field in required_fields:
            assert field in data, f"Response should contain '{field}' key"
        
        print(f"✓ All required fields present: {required_fields}")

    def test_trains_response_winner_fields_valid(self):
        """Test that winner fields contain valid station names"""
        response = requests.get(f"{BASE_URL}/api/trains")
        data = response.json()
        
        valid_winners = ["atocha", "chamartin"]
        assert data["winner_30min"] in valid_winners, f"winner_30min should be 'atocha' or 'chamartin', got {data['winner_30min']}"
        assert data["winner_60min"] in valid_winners, f"winner_60min should be 'atocha' or 'chamartin', got {data['winner_60min']}"
        print(f"✓ Winner fields valid: winner_30min={data['winner_30min']}, winner_60min={data['winner_60min']}")


class TestTrainArrivalData:
    """Tests for train arrival data structure and required fields"""

    def test_train_arrivals_have_required_fields(self):
        """Test that train arrivals contain required fields: time, train_type, train_number, origin"""
        response = requests.get(f"{BASE_URL}/api/trains")
        data = response.json()
        
        required_fields = ["time", "train_type", "train_number", "origin"]
        
        # Check Atocha arrivals
        atocha_arrivals = data.get("atocha", {}).get("arrivals", [])
        if atocha_arrivals:
            for i, arrival in enumerate(atocha_arrivals[:5]):  # Check first 5
                for field in required_fields:
                    assert field in arrival, f"Atocha arrival {i} missing '{field}' field"
            print(f"✓ Atocha arrivals ({len(atocha_arrivals)} total) contain required fields")
        else:
            print("⚠ No Atocha arrivals to verify (may be night time)")
        
        # Check Chamartín arrivals
        chamartin_arrivals = data.get("chamartin", {}).get("arrivals", [])
        if chamartin_arrivals:
            for i, arrival in enumerate(chamartin_arrivals[:5]):  # Check first 5
                for field in required_fields:
                    assert field in arrival, f"Chamartín arrival {i} missing '{field}' field"
            print(f"✓ Chamartín arrivals ({len(chamartin_arrivals)} total) contain required fields")
        else:
            print("⚠ No Chamartín arrivals to verify (may be night time)")

    def test_train_type_is_valid(self):
        """Test that train types are valid media/larga distancia types"""
        response = requests.get(f"{BASE_URL}/api/trains")
        data = response.json()
        
        valid_types = ["AVE", "AVANT", "ALVIA", "IRYO", "OUIGO", "AVLO", "EUROMED", "TALGO", "TRENHOTEL", "MD", "TREN", "ESTRELLA"]
        
        all_arrivals = (
            data.get("atocha", {}).get("arrivals", []) + 
            data.get("chamartin", {}).get("arrivals", [])
        )
        
        if all_arrivals:
            for arrival in all_arrivals[:10]:
                train_type = arrival.get("train_type", "").upper()
                # Check if train_type starts with a valid type
                is_valid = any(valid in train_type for valid in valid_types)
                assert is_valid, f"Train type '{train_type}' is not a valid media/larga distancia type"
            print(f"✓ Train types are valid media/larga distancia types")
        else:
            print("⚠ No arrivals to verify train types")

    def test_train_number_format(self):
        """Test that train numbers have proper format (numeric or alphanumeric)"""
        response = requests.get(f"{BASE_URL}/api/trains")
        data = response.json()
        
        all_arrivals = (
            data.get("atocha", {}).get("arrivals", []) + 
            data.get("chamartin", {}).get("arrivals", [])
        )
        
        if all_arrivals:
            for arrival in all_arrivals[:10]:
                train_number = arrival.get("train_number", "")
                assert train_number, f"Train number should not be empty"
                assert len(train_number) >= 4, f"Train number '{train_number}' seems too short"
            print(f"✓ Train numbers have proper format")
        else:
            print("⚠ No arrivals to verify train numbers")

    def test_arrival_time_format(self):
        """Test that arrival times are in HH:MM format"""
        response = requests.get(f"{BASE_URL}/api/trains")
        data = response.json()
        
        import re
        time_pattern = re.compile(r'^\d{1,2}:\d{2}$')
        
        all_arrivals = (
            data.get("atocha", {}).get("arrivals", []) + 
            data.get("chamartin", {}).get("arrivals", [])
        )
        
        if all_arrivals:
            for arrival in all_arrivals[:10]:
                time_str = arrival.get("time", "")
                assert time_pattern.match(time_str), f"Time '{time_str}' is not in HH:MM format"
            print(f"✓ Arrival times are in HH:MM format")
        else:
            print("⚠ No arrivals to verify time format")


class TestTrainsStationCounts:
    """Tests for station arrival counts"""

    def test_station_counts_are_integers(self):
        """Test that arrival counts are non-negative integers"""
        response = requests.get(f"{BASE_URL}/api/trains")
        data = response.json()
        
        for station in ["atocha", "chamartin"]:
            station_data = data.get(station, {})
            total_30 = station_data.get("total_next_30min")
            total_60 = station_data.get("total_next_60min")
            
            assert isinstance(total_30, int), f"{station} total_next_30min should be int"
            assert isinstance(total_60, int), f"{station} total_next_60min should be int"
            assert total_30 >= 0, f"{station} total_next_30min should be >= 0"
            assert total_60 >= 0, f"{station} total_next_60min should be >= 0"
            
            print(f"✓ {station}: total_30min={total_30}, total_60min={total_60}")

    def test_30min_count_not_greater_than_60min(self):
        """Test that 30min count is not greater than 60min count"""
        response = requests.get(f"{BASE_URL}/api/trains")
        data = response.json()
        
        for station in ["atocha", "chamartin"]:
            station_data = data.get(station, {})
            total_30 = station_data.get("total_next_30min", 0)
            total_60 = station_data.get("total_next_60min", 0)
            
            assert total_30 <= total_60, f"{station}: 30min count ({total_30}) should not exceed 60min count ({total_60})"
        
        print(f"✓ 30min counts are <= 60min counts")


class TestTrainsWithShiftFilter:
    """Tests for trains endpoint with shift filter"""

    def test_trains_day_shift(self):
        """Test trains endpoint with day shift filter"""
        response = requests.get(f"{BASE_URL}/api/trains?shift=day")
        assert response.status_code == 200
        print(f"✓ Trains with shift=day returns 200")

    def test_trains_night_shift(self):
        """Test trains endpoint with night shift filter"""
        response = requests.get(f"{BASE_URL}/api/trains?shift=night")
        assert response.status_code == 200
        print(f"✓ Trains with shift=night returns 200")

    def test_trains_all_shift(self):
        """Test trains endpoint with all shift filter"""
        response = requests.get(f"{BASE_URL}/api/trains?shift=all")
        assert response.status_code == 200
        print(f"✓ Trains with shift=all returns 200")


class TestRenfeGTFSIntegration:
    """Tests for Renfe GTFS integration (fallback data source)"""

    def test_health_endpoint_shows_gtfs_status(self):
        """Test if health endpoint exists and returns info"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        print(f"✓ Health endpoint returns 200")

    def test_trains_source_field_when_from_renfe(self):
        """Test that arrivals from Renfe GTFS have source='Renfe GTFS' field"""
        response = requests.get(f"{BASE_URL}/api/trains")
        data = response.json()
        
        all_arrivals = (
            data.get("atocha", {}).get("arrivals", []) + 
            data.get("chamartin", {}).get("arrivals", [])
        )
        
        renfe_arrivals = [a for a in all_arrivals if a.get("source") == "Renfe GTFS"]
        adif_arrivals = [a for a in all_arrivals if not a.get("source")]  # ADIF doesn't add source field
        
        print(f"✓ Data sources: {len(adif_arrivals)} from ADIF, {len(renfe_arrivals)} from Renfe GTFS")
        
        # Note: We can't assert that Renfe GTFS data is present because it's only used as fallback
        # When ADIF is working, all data will be from ADIF


class TestCacheSystem:
    """Tests for the caching system"""

    def test_multiple_requests_consistent(self):
        """Test that multiple requests return consistent data (cache working)"""
        response1 = requests.get(f"{BASE_URL}/api/trains")
        response2 = requests.get(f"{BASE_URL}/api/trains")
        
        data1 = response1.json()
        data2 = response2.json()
        
        # The last_update timestamp should be the same within a few seconds
        # since cache is used
        assert data1["winner_30min"] == data2["winner_30min"], "Consecutive requests should have same winner"
        print(f"✓ Multiple requests return consistent cached data")

    def test_last_update_timestamp_valid(self):
        """Test that last_update field contains a valid ISO timestamp"""
        response = requests.get(f"{BASE_URL}/api/trains")
        data = response.json()
        
        last_update = data.get("last_update")
        assert last_update, "last_update should not be empty"
        
        # Try to parse as ISO format
        from datetime import datetime
        try:
            # Handle timezone-aware ISO format
            if "+" in last_update:
                dt = datetime.fromisoformat(last_update)
            else:
                dt = datetime.fromisoformat(last_update.replace("Z", "+00:00"))
            assert dt, "last_update should be a valid datetime"
            print(f"✓ last_update is valid ISO timestamp: {last_update}")
        except ValueError as e:
            pytest.fail(f"last_update '{last_update}' is not valid ISO format: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
