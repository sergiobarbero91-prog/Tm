"""
Tests for authentication endpoints.
"""
import pytest
from httpx import AsyncClient


class TestAuth:
    """Test authentication endpoints."""

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client: AsyncClient):
        """Test health endpoint returns 200."""
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_register_new_user(self, client: AsyncClient):
        """Test user registration."""
        import uuid
        unique_username = f"test_user_{uuid.uuid4().hex[:8]}"
        
        response = await client.post("/api/auth/register", json={
            "username": unique_username,
            "password": "testpassword123",
            "full_name": "Test User",
            "license_number": str(uuid.uuid4().int)[:5]
        })
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["username"] == unique_username

    @pytest.mark.asyncio
    async def test_register_duplicate_username(self, client: AsyncClient):
        """Test that duplicate username registration fails."""
        import uuid
        unique_username = f"test_dup_{uuid.uuid4().hex[:8]}"
        
        # First registration
        await client.post("/api/auth/register", json={
            "username": unique_username,
            "password": "testpassword123",
            "full_name": "Test User",
            "license_number": str(uuid.uuid4().int)[:5]
        })
        
        # Duplicate registration
        response = await client.post("/api/auth/register", json={
            "username": unique_username,
            "password": "testpassword123",
            "full_name": "Test User 2",
            "license_number": str(uuid.uuid4().int)[:5]
        })
        
        assert response.status_code == 400
        assert "ya existe" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_login_valid_credentials(self, client: AsyncClient):
        """Test login with valid credentials."""
        import uuid
        unique_username = f"test_login_{uuid.uuid4().hex[:8]}"
        
        # Register first
        await client.post("/api/auth/register", json={
            "username": unique_username,
            "password": "testpassword123",
            "full_name": "Test User",
            "license_number": str(uuid.uuid4().int)[:5]
        })
        
        # Login
        response = await client.post("/api/auth/login", json={
            "username": unique_username,
            "password": "testpassword123"
        })
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, client: AsyncClient):
        """Test login with invalid credentials."""
        response = await client.post("/api/auth/login", json={
            "username": "nonexistent_user",
            "password": "wrongpassword"
        })
        
        assert response.status_code == 401
        assert "incorrectos" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_current_user(self, authenticated_client: AsyncClient):
        """Test getting current user profile."""
        response = await authenticated_client.get("/api/auth/me")
        
        assert response.status_code == 200
        data = response.json()
        assert "username" in data
        assert "full_name" in data

    @pytest.mark.asyncio
    async def test_protected_endpoint_without_auth(self, client: AsyncClient):
        """Test that protected endpoints require authentication."""
        response = await client.get("/api/auth/me")
        
        assert response.status_code == 401


class TestTrainsAPI:
    """Test trains API endpoints."""

    @pytest.mark.asyncio
    async def test_get_trains(self, client: AsyncClient):
        """Test getting train data."""
        response = await client.get("/api/trains?window_minutes=60")
        
        assert response.status_code == 200
        data = response.json()
        assert "atocha" in data
        assert "chamartin" in data

    @pytest.mark.asyncio
    async def test_get_trains_with_shift(self, client: AsyncClient):
        """Test getting train data with shift filter."""
        response = await client.get("/api/trains?window_minutes=60&shift=day")
        
        assert response.status_code == 200


class TestFlightsAPI:
    """Test flights API endpoints."""

    @pytest.mark.asyncio
    async def test_get_flights(self, client: AsyncClient):
        """Test getting flight data."""
        response = await client.get("/api/flights?window_minutes=60")
        
        assert response.status_code == 200
        data = response.json()
        assert "terminals" in data


class TestStationAlerts:
    """Test station alerts endpoints."""

    @pytest.mark.asyncio
    async def test_get_active_alerts(self, client: AsyncClient):
        """Test getting active alerts."""
        response = await client.get("/api/station-alerts/active")
        
        assert response.status_code == 200
        data = response.json()
        assert "alerts" in data
        assert "stations_with_alerts" in data
        assert "terminals_with_alerts" in data

    @pytest.mark.asyncio
    async def test_create_alert_requires_auth(self, client: AsyncClient):
        """Test that creating alerts requires authentication."""
        response = await client.post("/api/station-alerts/create", json={
            "location_type": "station",
            "location_name": "atocha",
            "alert_type": "sin_taxis"
        })
        
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_create_alert_authenticated(self, authenticated_client: AsyncClient):
        """Test creating an alert when authenticated."""
        response = await authenticated_client.post("/api/station-alerts/create", json={
            "location_type": "station",
            "location_name": "atocha",
            "alert_type": "sin_taxis"
        })
        
        # Should be 200 or 400 (if user already has an active alert)
        assert response.status_code in [200, 400]


class TestChat:
    """Test chat endpoints."""

    @pytest.mark.asyncio
    async def test_get_channels(self, client: AsyncClient):
        """Test getting available chat channels."""
        response = await client.get("/api/chat/channels")
        
        assert response.status_code == 200
        data = response.json()
        assert "channels" in data
        assert len(data["channels"]) > 0

    @pytest.mark.asyncio
    async def test_send_message_requires_auth(self, client: AsyncClient):
        """Test that sending messages requires authentication."""
        response = await client.post("/api/chat/general/messages", json={
            "message": "Test message"
        })
        
        assert response.status_code == 401
