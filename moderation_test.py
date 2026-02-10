#!/usr/bin/env python3
"""
Backend Test Suite for Moderation System
Tests the recently implemented moderation and reports system
"""

import requests
import json
import sys
from datetime import datetime
from typing import Dict, Any, Optional

# Configuration
BASE_URL = "https://train-scraper-fix.preview.emergentagent.com/api"
ADMIN_CREDENTIALS = {"username": "admin", "password": "admin"}

class ModerationTester:
    def __init__(self):
        self.session = requests.Session()
        self.admin_token = None
        self.test_results = []
        
    def log_test(self, test_name: str, success: bool, details: str = "", response_data: Any = None):
        """Log test result"""
        result = {
            "test": test_name,
            "success": success,
            "details": details,
            "timestamp": datetime.now().isoformat(),
            "response_data": response_data
        }
        self.test_results.append(result)
        
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}")
        if details:
            print(f"    Details: {details}")
        if not success and response_data:
            print(f"    Response: {response_data}")
        print()

    def login_admin(self) -> bool:
        """Login as admin user"""
        try:
            response = self.session.post(
                f"{BASE_URL}/auth/login",
                json=ADMIN_CREDENTIALS,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                self.admin_token = data.get("access_token")
                if self.admin_token:
                    self.session.headers.update({
                        "Authorization": f"Bearer {self.admin_token}"
                    })
                    self.log_test("Admin Login", True, f"Logged in as {data.get('user', {}).get('username')}")
                    return True
                else:
                    self.log_test("Admin Login", False, "No access token in response", data)
                    return False
            else:
                self.log_test("Admin Login", False, f"HTTP {response.status_code}", response.text)
                return False
                
        except Exception as e:
            self.log_test("Admin Login", False, f"Exception: {str(e)}")
            return False

    def test_create_report(self) -> Optional[str]:
        """Test POST /api/moderation/reports - Create a report"""
        try:
            report_data = {
                "report_type": "spam",
                "description": "Este es un reporte de prueba con más de 10 caracteres para validar el sistema de moderación"
            }
            
            response = self.session.post(
                f"{BASE_URL}/moderation/reports",
                json=report_data,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success") and data.get("report_id"):
                    self.log_test(
                        "Create Report", 
                        True, 
                        f"Report created with ID: {data.get('report_id')}", 
                        data
                    )
                    return data.get("report_id")
                else:
                    self.log_test("Create Report", False, "Missing success or report_id in response", data)
                    return None
            else:
                self.log_test("Create Report", False, f"HTTP {response.status_code}", response.text)
                return None
                
        except Exception as e:
            self.log_test("Create Report", False, f"Exception: {str(e)}")
            return None

    def test_get_report_types(self) -> bool:
        """Test GET /api/moderation/reports/types - Get report types"""
        try:
            response = self.session.get(
                f"{BASE_URL}/moderation/reports/types",
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                types = data.get("types", [])
                
                # Check if all expected types are present
                expected_types = ["inappropriate", "spam", "false_info", "harassment", "other"]
                found_types = [t.get("id") for t in types if isinstance(t, dict)]
                
                if len(types) == 5 and all(t in found_types for t in expected_types):
                    self.log_test(
                        "Get Report Types", 
                        True, 
                        f"Found all 5 expected types: {found_types}", 
                        data
                    )
                    return True
                else:
                    self.log_test(
                        "Get Report Types", 
                        False, 
                        f"Expected 5 types {expected_types}, got {len(types)}: {found_types}", 
                        data
                    )
                    return False
            else:
                self.log_test("Get Report Types", False, f"HTTP {response.status_code}", response.text)
                return False
                
        except Exception as e:
            self.log_test("Get Report Types", False, f"Exception: {str(e)}")
            return False

    def test_get_pending_reports(self) -> bool:
        """Test GET /api/moderation/reports/pending-moderator - Get pending reports"""
        try:
            response = self.session.get(
                f"{BASE_URL}/moderation/reports/pending-moderator",
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                reports = data.get("reports", [])
                total = data.get("total", 0)
                
                if isinstance(reports, list) and isinstance(total, int):
                    self.log_test(
                        "Get Pending Reports", 
                        True, 
                        f"Found {total} pending reports", 
                        {"total": total, "sample_count": len(reports)}
                    )
                    return True
                else:
                    self.log_test("Get Pending Reports", False, "Invalid response structure", data)
                    return False
            else:
                self.log_test("Get Pending Reports", False, f"HTTP {response.status_code}", response.text)
                return False
                
        except Exception as e:
            self.log_test("Get Pending Reports", False, f"Exception: {str(e)}")
            return False

    def test_get_moderator_stats(self) -> bool:
        """Test GET /api/moderation/stats/moderator - Get moderation stats"""
        try:
            response = self.session.get(
                f"{BASE_URL}/moderation/stats/moderator",
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Check required fields
                required_fields = ["pending_reports", "pending_promotions"]
                if all(field in data for field in required_fields):
                    self.log_test(
                        "Get Moderator Stats", 
                        True, 
                        f"Pending reports: {data.get('pending_reports')}, Pending promotions: {data.get('pending_promotions')}", 
                        data
                    )
                    return True
                else:
                    missing = [f for f in required_fields if f not in data]
                    self.log_test("Get Moderator Stats", False, f"Missing fields: {missing}", data)
                    return False
            else:
                self.log_test("Get Moderator Stats", False, f"HTTP {response.status_code}", response.text)
                return False
                
        except Exception as e:
            self.log_test("Get Moderator Stats", False, f"Exception: {str(e)}")
            return False

    def test_get_pending_promotions(self) -> bool:
        """Test GET /api/moderation/promotions/pending-moderator - Get pending promotions"""
        try:
            response = self.session.get(
                f"{BASE_URL}/moderation/promotions/pending-moderator",
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                requests_list = data.get("requests", [])
                total = data.get("total", 0)
                
                if isinstance(requests_list, list) and isinstance(total, int):
                    self.log_test(
                        "Get Pending Promotions", 
                        True, 
                        f"Found {total} pending promotion requests", 
                        {"total": total, "sample_count": len(requests_list)}
                    )
                    return True
                else:
                    self.log_test("Get Pending Promotions", False, "Invalid response structure", data)
                    return False
            else:
                self.log_test("Get Pending Promotions", False, f"HTTP {response.status_code}", response.text)
                return False
                
        except Exception as e:
            self.log_test("Get Pending Promotions", False, f"Exception: {str(e)}")
            return False

    def test_invalid_report_creation(self) -> bool:
        """Test validation for report creation"""
        try:
            # Test with invalid report type
            invalid_report = {
                "report_type": "invalid_type",
                "description": "This should fail due to invalid type"
            }
            
            response = self.session.post(
                f"{BASE_URL}/moderation/reports",
                json=invalid_report,
                timeout=10
            )
            
            if response.status_code == 400:
                self.log_test(
                    "Invalid Report Type Validation", 
                    True, 
                    "Correctly rejected invalid report type", 
                    response.text
                )
            else:
                self.log_test(
                    "Invalid Report Type Validation", 
                    False, 
                    f"Expected 400, got {response.status_code}", 
                    response.text
                )
                return False

            # Test with short description
            short_desc_report = {
                "report_type": "spam",
                "description": "Short"  # Less than 10 characters
            }
            
            response = self.session.post(
                f"{BASE_URL}/moderation/reports",
                json=short_desc_report,
                timeout=10
            )
            
            if response.status_code == 400:
                self.log_test(
                    "Short Description Validation", 
                    True, 
                    "Correctly rejected short description", 
                    response.text
                )
                return True
            else:
                self.log_test(
                    "Short Description Validation", 
                    False, 
                    f"Expected 400, got {response.status_code}", 
                    response.text
                )
                return False
                
        except Exception as e:
            self.log_test("Report Validation Tests", False, f"Exception: {str(e)}")
            return False

    def run_all_tests(self):
        """Run all moderation system tests"""
        print("🧪 Starting Moderation System Tests")
        print("=" * 50)
        
        # Login first
        if not self.login_admin():
            print("❌ Cannot proceed without admin login")
            return False
        
        # Run all tests
        tests_passed = 0
        total_tests = 0
        
        # Core functionality tests
        test_methods = [
            self.test_get_report_types,
            self.test_create_report,
            self.test_get_pending_reports,
            self.test_get_moderator_stats,
            self.test_get_pending_promotions,
            self.test_invalid_report_creation
        ]
        
        for test_method in test_methods:
            total_tests += 1
            try:
                if test_method():
                    tests_passed += 1
            except Exception as e:
                print(f"❌ Test {test_method.__name__} failed with exception: {e}")
        
        # Summary
        print("=" * 50)
        print(f"📊 Test Summary: {tests_passed}/{total_tests} tests passed")
        
        if tests_passed == total_tests:
            print("🎉 All moderation system tests PASSED!")
            return True
        else:
            print(f"⚠️  {total_tests - tests_passed} test(s) FAILED")
            return False

    def print_detailed_results(self):
        """Print detailed test results"""
        print("\n" + "=" * 60)
        print("📋 DETAILED TEST RESULTS")
        print("=" * 60)
        
        for result in self.test_results:
            status = "✅ PASS" if result["success"] else "❌ FAIL"
            print(f"\n{status} {result['test']}")
            print(f"   Time: {result['timestamp']}")
            if result['details']:
                print(f"   Details: {result['details']}")
            if result['response_data'] and not result["success"]:
                print(f"   Response: {json.dumps(result['response_data'], indent=2)}")


def main():
    """Main test execution"""
    print("🚀 Backend Moderation System Test Suite")
    print(f"🌐 Testing against: {BASE_URL}")
    print()
    
    tester = ModerationTester()
    
    try:
        success = tester.run_all_tests()
        tester.print_detailed_results()
        
        # Exit with appropriate code
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        print("\n⏹️  Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()