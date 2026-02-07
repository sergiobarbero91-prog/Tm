#!/usr/bin/env python3
"""
Backend Test Suite for Points/Gamification System
Tests the points API endpoints and event voting functionality
"""

import asyncio
import aiohttp
import json
import os
from datetime import datetime
from typing import Dict, Any, Optional

# Get backend URL from environment
BACKEND_URL = os.getenv('EXPO_PUBLIC_BACKEND_URL', 'https://clouding-preview.preview.emergentagent.com')
API_BASE = f"{BACKEND_URL}/api"

class PointsSystemTester:
    def __init__(self):
        self.session = None
        self.admin_token = None
        self.test_user_token = None
        self.test_results = []
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def log_result(self, test_name: str, success: bool, message: str, details: Any = None):
        """Log test result"""
        result = {
            "test": test_name,
            "success": success,
            "message": message,
            "details": details,
            "timestamp": datetime.now().isoformat()
        }
        self.test_results.append(result)
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}: {message}")
        if details and not success:
            print(f"   Details: {details}")
    
    async def make_request(self, method: str, endpoint: str, token: str = None, data: dict = None) -> tuple[bool, dict]:
        """Make HTTP request with error handling"""
        url = f"{API_BASE}{endpoint}"
        headers = {"Content-Type": "application/json"}
        
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        try:
            async with self.session.request(method, url, headers=headers, json=data) as response:
                response_data = await response.json()
                return response.status < 400, response_data
        except Exception as e:
            return False, {"error": str(e)}
    
    async def login_admin(self) -> bool:
        """Login as admin user"""
        success, data = await self.make_request("POST", "/auth/login", data={
            "username": "admin",
            "password": "admin"
        })
        
        if success and "access_token" in data:
            self.admin_token = data["access_token"]
            self.log_result("Admin Login", True, "Successfully logged in as admin")
            return True
        else:
            self.log_result("Admin Login", False, "Failed to login as admin", data)
            return False
    
    async def test_get_my_points(self) -> bool:
        """Test GET /api/points/my-points endpoint"""
        success, data = await self.make_request("GET", "/points/my-points", self.admin_token)
        
        if success:
            # Verify response structure
            required_fields = ["total_points", "level_name", "level_badge", "next_level_name", "points_to_next_level", "history"]
            missing_fields = [field for field in required_fields if field not in data]
            
            if missing_fields:
                self.log_result("Get My Points", False, f"Missing fields: {missing_fields}", data)
                return False
            
            # Verify data types
            if not isinstance(data["total_points"], int):
                self.log_result("Get My Points", False, "total_points should be integer", data)
                return False
            
            if not isinstance(data["history"], list):
                self.log_result("Get My Points", False, "history should be list", data)
                return False
            
            self.log_result("Get My Points", True, f"Points: {data['total_points']}, Level: {data['level_name']} {data['level_badge']}")
            return True
        else:
            self.log_result("Get My Points", False, "Failed to get user points", data)
            return False
    
    async def test_get_ranking(self) -> bool:
        """Test GET /api/points/ranking endpoint"""
        success, data = await self.make_request("GET", "/points/ranking", self.admin_token)
        
        if success:
            # Verify response structure
            required_fields = ["ranking", "my_position", "total_users"]
            missing_fields = [field for field in required_fields if field not in data]
            
            if missing_fields:
                self.log_result("Get Ranking", False, f"Missing fields: {missing_fields}", data)
                return False
            
            # Verify ranking structure
            if not isinstance(data["ranking"], list):
                self.log_result("Get Ranking", False, "ranking should be list", data)
                return False
            
            # Check ranking entry structure if any users exist
            if data["ranking"]:
                first_user = data["ranking"][0]
                required_user_fields = ["position", "user_id", "username", "total_points", "level_name", "level_badge", "is_me"]
                missing_user_fields = [field for field in required_user_fields if field not in first_user]
                
                if missing_user_fields:
                    self.log_result("Get Ranking", False, f"Missing user fields: {missing_user_fields}", first_user)
                    return False
            
            self.log_result("Get Ranking", True, f"Found {len(data['ranking'])} users in ranking, total users: {data['total_users']}")
            return True
        else:
            self.log_result("Get Ranking", False, "Failed to get ranking", data)
            return False
    
    async def test_get_points_config(self) -> bool:
        """Test GET /api/points/config endpoint"""
        success, data = await self.make_request("GET", "/points/config", self.admin_token)
        
        if success:
            # Verify response structure
            required_fields = ["actions", "levels"]
            missing_fields = [field for field in required_fields if field not in data]
            
            if missing_fields:
                self.log_result("Get Points Config", False, f"Missing fields: {missing_fields}", data)
                return False
            
            # Verify actions structure
            if not isinstance(data["actions"], dict):
                self.log_result("Get Points Config", False, "actions should be dict", data)
                return False
            
            # Verify levels structure
            if not isinstance(data["levels"], list):
                self.log_result("Get Points Config", False, "levels should be list", data)
                return False
            
            # Check if expected actions exist
            expected_actions = ["checkin", "checkout", "alert_real", "receive_like", "invite_used", "approve_registration"]
            missing_actions = [action for action in expected_actions if action not in data["actions"]]
            
            if missing_actions:
                self.log_result("Get Points Config", False, f"Missing actions: {missing_actions}", data["actions"])
                return False
            
            self.log_result("Get Points Config", True, f"Found {len(data['actions'])} actions and {len(data['levels'])} levels")
            return True
        else:
            self.log_result("Get Points Config", False, "Failed to get points config", data)
            return False
    
    async def test_create_event(self) -> Optional[str]:
        """Test creating an event and return event_id"""
        event_data = {
            "location": "Plaza de Cibeles",
            "description": "Control de policía - velocidad",
            "event_time": "14:30"
        }
        
        success, data = await self.make_request("POST", "/events", self.admin_token, event_data)
        
        if success and data.get("success") and "event_id" in data:
            event_id = data["event_id"]
            self.log_result("Create Event", True, f"Created event with ID: {event_id}")
            return event_id
        else:
            self.log_result("Create Event", False, "Failed to create event", data)
            return None
    
    async def test_vote_event_points(self, event_id: str) -> bool:
        """Test voting on event and verify points are awarded"""
        # First, get current points
        success, points_before = await self.make_request("GET", "/points/my-points", self.admin_token)
        if not success:
            self.log_result("Vote Event Points", False, "Failed to get points before voting", points_before)
            return False
        
        initial_points = points_before["total_points"]
        
        # Vote on the event (like)
        vote_data = {"vote_type": "like"}
        success, vote_response = await self.make_request("POST", f"/events/{event_id}/vote", self.admin_token, vote_data)
        
        if not success:
            self.log_result("Vote Event Points", False, "Failed to vote on event", vote_response)
            return False
        
        # Wait a moment for points to be processed
        await asyncio.sleep(1)
        
        # Get points after voting
        success, points_after = await self.make_request("GET", "/points/my-points", self.admin_token)
        if not success:
            self.log_result("Vote Event Points", False, "Failed to get points after voting", points_after)
            return False
        
        final_points = points_after["total_points"]
        
        # Since admin is voting on their own event, they should NOT receive points
        # (self-voting doesn't award points)
        if final_points == initial_points:
            self.log_result("Vote Event Points", True, f"Correctly no points awarded for self-voting (points remained {final_points})")
            return True
        else:
            self.log_result("Vote Event Points", False, f"Unexpected points change: {initial_points} -> {final_points}")
            return False
    
    async def create_test_user(self) -> Optional[str]:
        """Create a test user via invitation system"""
        # First create an invitation as admin
        invitation_data = {"note": "Test user for points testing"}
        success, invite_response = await self.make_request("POST", "/auth/invitations", self.admin_token, invitation_data)
        
        if not success or "code" not in invite_response:
            self.log_result("Create Test User", False, "Failed to create invitation", invite_response)
            return None
        
        invitation_code = invite_response["code"]
        
        # Register new user with invitation
        register_data = {
            "invitation_code": invitation_code,
            "username": "testuser123",
            "password": "testpass123",
            "full_name": "Test User",
            "license_number": "12345",
            "phone": "+34600123456",
            "preferred_shift": "all"
        }
        
        success, register_response = await self.make_request("POST", "/auth/register-with-invitation", data=register_data)
        
        if success and "access_token" in register_response:
            self.test_user_token = register_response["access_token"]
            self.log_result("Create Test User", True, f"Created test user: testuser123")
            return self.test_user_token
        else:
            self.log_result("Create Test User", False, "Failed to register test user", register_response)
            return None

    async def test_event_like_points_different_user(self) -> bool:
        """Test that points are awarded when different user likes an event"""
        # Create a test user first
        test_token = await self.create_test_user()
        if not test_token:
            return False
        
        # Admin creates an event
        event_data = {
            "location": "Aeropuerto T4",
            "description": "Mucho tráfico en llegadas",
            "event_time": "15:45"
        }
        
        success, event_response = await self.make_request("POST", "/events", self.admin_token, event_data)
        if not success or not event_response.get("success"):
            self.log_result("Event Like Points Different User", False, "Failed to create event", event_response)
            return False
        
        event_id = event_response["event_id"]
        
        # Get admin's points before the like
        success, points_before = await self.make_request("GET", "/points/my-points", self.admin_token)
        if not success:
            self.log_result("Event Like Points Different User", False, "Failed to get admin points before", points_before)
            return False
        
        initial_points = points_before["total_points"]
        
        # Test user likes the admin's event
        vote_data = {"vote_type": "like"}
        success, vote_response = await self.make_request("POST", f"/events/{event_id}/vote", test_token, vote_data)
        
        if not success:
            self.log_result("Event Like Points Different User", False, "Failed to vote on event", vote_response)
            return False
        
        # Wait for points to be processed
        await asyncio.sleep(1)
        
        # Get admin's points after the like
        success, points_after = await self.make_request("GET", "/points/my-points", self.admin_token)
        if not success:
            self.log_result("Event Like Points Different User", False, "Failed to get admin points after", points_after)
            return False
        
        final_points = points_after["total_points"]
        points_gained = final_points - initial_points
        
        # Admin should have received 5 points for the like
        if points_gained == 5:
            self.log_result("Event Like Points Different User", True, f"Admin correctly received 5 points for event like ({initial_points} -> {final_points})")
            return True
        else:
            self.log_result("Event Like Points Different User", False, f"Expected 5 points, got {points_gained} points ({initial_points} -> {final_points})")
            return False

    async def test_invitation_points(self) -> bool:
        """Test that points are awarded for successful invitations"""
        # Get admin's points before creating invitation
        success, points_before = await self.make_request("GET", "/points/my-points", self.admin_token)
        if not success:
            self.log_result("Invitation Points", False, "Failed to get admin points before", points_before)
            return False
        
        initial_points = points_before["total_points"]
        
        # Create invitation
        invitation_data = {"note": "Test invitation for points"}
        success, invite_response = await self.make_request("POST", "/auth/invitations", self.admin_token, invitation_data)
        
        if not success or "code" not in invite_response:
            self.log_result("Invitation Points", False, "Failed to create invitation", invite_response)
            return False
        
        invitation_code = invite_response["code"]
        
        # Register new user with invitation
        register_data = {
            "invitation_code": invitation_code,
            "username": "invitetest456",
            "password": "testpass456",
            "full_name": "Invite Test User",
            "license_number": "67890",
            "phone": "+34600456789",
            "preferred_shift": "day"
        }
        
        success, register_response = await self.make_request("POST", "/auth/register-with-invitation", data=register_data)
        
        if not success:
            self.log_result("Invitation Points", False, "Failed to register with invitation", register_response)
            return False
        
        # Wait for points to be processed
        await asyncio.sleep(1)
        
        # Get admin's points after invitation is used
        success, points_after = await self.make_request("GET", "/points/my-points", self.admin_token)
        if not success:
            self.log_result("Invitation Points", False, "Failed to get admin points after", points_after)
            return False
        
        final_points = points_after["total_points"]
        points_gained = final_points - initial_points
        
        # Admin should have received 50 points for successful invitation
        if points_gained == 50:
            self.log_result("Invitation Points", True, f"Admin correctly received 50 points for invitation ({initial_points} -> {final_points})")
            return True
        else:
            self.log_result("Invitation Points", False, f"Expected 50 points, got {points_gained} points ({initial_points} -> {final_points})")
            return False
    
    async def run_all_tests(self):
        """Run all tests in sequence"""
        print("🚀 Starting Points System Backend Tests")
        print(f"Backend URL: {BACKEND_URL}")
        print("=" * 60)
        
        # Login first
        if not await self.login_admin():
            print("❌ Cannot proceed without admin login")
            return
        
        # Test all endpoints
        tests = [
            self.test_get_my_points,
            self.test_get_ranking,
            self.test_get_points_config,
            self.test_invitation_points,
            self.test_event_like_points_different_user,
        ]
        
        for test in tests:
            try:
                await test()
            except Exception as e:
                self.log_result(test.__name__, False, f"Test failed with exception: {str(e)}")
            
            # Small delay between tests
            await asyncio.sleep(0.5)
        
        # Summary
        print("\n" + "=" * 60)
        print("📊 TEST SUMMARY")
        print("=" * 60)
        
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        
        print(f"Total Tests: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {total - passed}")
        print(f"Success Rate: {(passed/total*100):.1f}%")
        
        # Show failed tests
        failed_tests = [result for result in self.test_results if not result["success"]]
        if failed_tests:
            print("\n❌ FAILED TESTS:")
            for result in failed_tests:
                print(f"  - {result['test']}: {result['message']}")
        
        print("\n✅ Test run completed!")
        return passed == total

async def main():
    """Main test runner"""
    async with PointsSystemTester() as tester:
        success = await tester.run_all_tests()
        return success

if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)