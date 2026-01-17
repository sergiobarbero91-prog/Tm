"""
Test configuration and fixtures for pytest.
"""
import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from motor.motor_asyncio import AsyncIOMotorClient
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app

# Test database name
TEST_DB_NAME = "transport_meter_test"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def client():
    """Create async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def authenticated_client(client):
    """Create authenticated test client with a test user."""
    # Register a test user
    register_response = await client.post("/api/auth/register", json={
        "username": "test_user_pytest",
        "password": "testpassword123",
        "full_name": "Test User",
        "license_number": "99999"
    })
    
    if register_response.status_code == 400:
        # User exists, login instead
        login_response = await client.post("/api/auth/login", json={
            "username": "test_user_pytest",
            "password": "testpassword123"
        })
        token = login_response.json()["access_token"]
    else:
        token = register_response.json()["access_token"]
    
    # Create new client with auth header
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, 
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"}
    ) as ac:
        yield ac


@pytest.fixture
async def test_db():
    """Create test database connection."""
    mongo_url = os.getenv("MONGO_URL", "mongodb://localhost:27017")
    client = AsyncIOMotorClient(mongo_url)
    db = client[TEST_DB_NAME]
    yield db
    # Cleanup after tests
    await client.drop_database(TEST_DB_NAME)
    client.close()
