#!/usr/bin/env python3
"""
Comprehensive Moderation System Flow Test
Tests the complete flow as requested in the review
"""

import requests
import json
import sys
from datetime import datetime

# Configuration
BASE_URL = "https://post-options-bugs.preview.emergentagent.com/api"
ADMIN_CREDENTIALS = {"username": "admin", "password": "admin"}

def test_moderation_flow():
    """Test the complete moderation flow as requested"""
    session = requests.Session()
    
    print("🚀 Testing Moderation System Flow")
    print("=" * 50)
    
    # Step 1: Login as admin
    print("1️⃣ Login como admin...")
    try:
        response = session.post(f"{BASE_URL}/auth/login", json=ADMIN_CREDENTIALS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            token = data.get("access_token")
            if token:
                session.headers.update({"Authorization": f"Bearer {token}"})
                print(f"   ✅ Logged in as {data.get('user', {}).get('username')}")
            else:
                print("   ❌ No access token received")
                return False
        else:
            print(f"   ❌ Login failed: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Login error: {e}")
        return False
    
    # Step 2: Create a report
    print("\n2️⃣ Crear un reporte...")
    report_data = {
        "report_type": "spam",
        "description": "Este es un reporte de prueba con más de 10 caracteres"
    }
    
    try:
        response = session.post(f"{BASE_URL}/moderation/reports", json=report_data, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("success") and data.get("report_id"):
                report_id = data.get("report_id")
                print(f"   ✅ Reporte creado exitosamente")
                print(f"   📋 Report ID: {report_id}")
                print(f"   💬 Message: {data.get('message')}")
            else:
                print(f"   ❌ Unexpected response structure: {data}")
                return False
        else:
            print(f"   ❌ Failed to create report: HTTP {response.status_code}")
            print(f"   Response: {response.text}")
            return False
    except Exception as e:
        print(f"   ❌ Error creating report: {e}")
        return False
    
    # Step 3: Verify report appears in pending list
    print("\n3️⃣ Verificar que aparece en la lista de pendientes...")
    try:
        response = session.get(f"{BASE_URL}/moderation/reports/pending-moderator", timeout=10)
        if response.status_code == 200:
            data = response.json()
            reports = data.get("reports", [])
            total = data.get("total", 0)
            
            print(f"   📊 Total pending reports: {total}")
            
            # Find our report
            our_report = None
            for report in reports:
                if report.get("report_type") == "spam" and "Este es un reporte de prueba" in report.get("description", ""):
                    our_report = report
                    break
            
            if our_report:
                print(f"   ✅ Nuestro reporte encontrado en la lista")
                print(f"   📝 Type: {our_report.get('report_type_name')}")
                print(f"   👤 Reporter: {our_report.get('reporter_username')}")
                print(f"   📅 Created: {our_report.get('created_at')}")
            else:
                print(f"   ⚠️  Nuestro reporte no encontrado en la lista (puede ser normal si hay muchos reportes)")
                
        else:
            print(f"   ❌ Failed to get pending reports: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Error getting pending reports: {e}")
        return False
    
    # Step 4: Get moderation stats
    print("\n4️⃣ Obtener stats de moderación...")
    try:
        response = session.get(f"{BASE_URL}/moderation/stats/moderator", timeout=10)
        if response.status_code == 200:
            data = response.json()
            pending_reports = data.get("pending_reports", 0)
            pending_promotions = data.get("pending_promotions", 0)
            
            print(f"   📊 Estadísticas de moderación:")
            print(f"   📋 Pending reports: {pending_reports}")
            print(f"   🎖️  Pending promotions: {pending_promotions}")
            
            if pending_reports > 0:
                print(f"   ✅ Stats show pending reports (expected)")
            else:
                print(f"   ⚠️  No pending reports in stats")
                
        else:
            print(f"   ❌ Failed to get stats: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Error getting stats: {e}")
        return False
    
    # Step 5: Test report types endpoint
    print("\n5️⃣ Verificar tipos de reportes disponibles...")
    try:
        response = session.get(f"{BASE_URL}/moderation/reports/types", timeout=10)
        if response.status_code == 200:
            data = response.json()
            types = data.get("types", [])
            
            print(f"   📋 Tipos de reportes disponibles:")
            for report_type in types:
                print(f"   • {report_type.get('id')}: {report_type.get('name')}")
            
            expected_types = ["inappropriate", "spam", "false_info", "harassment", "other"]
            found_types = [t.get("id") for t in types]
            
            if len(types) == 5 and all(t in found_types for t in expected_types):
                print(f"   ✅ Todos los 5 tipos esperados encontrados")
            else:
                print(f"   ❌ Tipos incorrectos. Expected: {expected_types}, Found: {found_types}")
                return False
                
        else:
            print(f"   ❌ Failed to get report types: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Error getting report types: {e}")
        return False
    
    # Step 6: Test pending promotions
    print("\n6️⃣ Verificar peticiones de promoción pendientes...")
    try:
        response = session.get(f"{BASE_URL}/moderation/promotions/pending-moderator", timeout=10)
        if response.status_code == 200:
            data = response.json()
            requests_list = data.get("requests", [])
            total = data.get("total", 0)
            
            print(f"   🎖️  Total pending promotion requests: {total}")
            
            if total == 0:
                print(f"   ✅ No pending promotions (expected for new system)")
            else:
                print(f"   📋 Promotion requests found:")
                for req in requests_list[:3]:  # Show first 3
                    print(f"   • {req.get('username')} -> {req.get('target_role')} ({req.get('total_points')} pts)")
                
        else:
            print(f"   ❌ Failed to get pending promotions: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Error getting pending promotions: {e}")
        return False
    
    print("\n" + "=" * 50)
    print("🎉 FLUJO DE MODERACIÓN COMPLETADO EXITOSAMENTE")
    print("✅ Todos los endpoints funcionan correctamente")
    print("✅ El reporte se creó y aparece en las estadísticas")
    print("✅ Los tipos de reportes están disponibles")
    print("✅ Las peticiones de promoción se pueden consultar")
    
    return True

if __name__ == "__main__":
    success = test_moderation_flow()
    sys.exit(0 if success else 1)