import httpx

BASE_URL = "http://127.0.0.1:8000"


def run():
    # Increased to 180 seconds to allow for Gemini API retries
    with httpx.Client(timeout=180.0) as client:
        print("--- 1. Submit complaint (Intake + Triage + Priority) ---")
        data = {
            "title": "Pothole in left wheel path near school gate",
            "description": "Two scooter riders almost fell this morning. Active injury risk.",
            "lat": "28.45952",
            "lng": "77.02663",
            "category_hint": "pothole",
            "reporter_id": "CIT-201",
            "ward": "WARD-12",
        }
        r = client.post(f"{BASE_URL}/api/complaints", data=data)
        print(f"Status: {r.status_code}")
        if r.status_code != 201:
            print("Failed:", r.text)
            return

        resp = r.json()
        complaint_id = resp["complaint_id"]
        asset_id = resp["asset_id"]
        print(f"Created: {complaint_id} (Asset: {asset_id})")
        print(
            f"AI Category: {resp['category']}, Urgency: {resp['urgency']}, Score: {resp['priority_score']}"
        )

        print("\n--- 2. Admin assigns ---")
        r = client.patch(
            f"{BASE_URL}/api/complaints/{complaint_id}/status",
            json={
                "actor_id": "ADM-01",
                "actor_type": "admin",
                "action": "assign",
                "assignee_department": "roads_maintenance",
            },
        )
        print(f"Status: {r.status_code} -> SubStatus: {r.json().get('sub_status')}")

        print("\n--- 3. Officer starts work ---")
        r = client.patch(
            f"{BASE_URL}/api/complaints/{complaint_id}/status",
            json={"actor_id": "OFF-117", "actor_type": "officer", "action": "start_work"},
        )
        print(f"Status: {r.status_code} -> SubStatus: {r.json().get('sub_status')}")

        print("\n--- 4. Asset Passport (Timeline) ---")
        r = client.get(f"{BASE_URL}/api/assets/{asset_id}/passport")
        passport = r.json()
        print(f"Events in chain: {len(passport['timeline'])}")
        for ev in passport["timeline"]:
            print(f"  [seq {ev['seq']}] {ev['event_type']}")

        print("\n--- 5. Verify Hash Chain ---")
        r = client.get(f"{BASE_URL}/api/assets/{asset_id}/verify-chain")
        print(f"Chain Valid: {r.json()['valid']}")

        print("\n--- 6. Illegal Transition (Admin tries to Accept) ---")
        r = client.patch(
            f"{BASE_URL}/api/complaints/{complaint_id}/status",
            json={"actor_id": "ADM-01", "actor_type": "admin", "action": "accept"},
        )
        print(f"Status: {r.status_code} (Expected 409)")
        print(f"Error: {r.json().get('code')} - {r.json().get('detail')}")


if __name__ == "__main__":
    run()
