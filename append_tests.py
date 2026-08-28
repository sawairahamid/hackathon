code = '''

def test_impact_generated_after_workflow():
    wid = "wf_impact_test"
    # Ensure it's a new test DB execution
    status = _run(PRIMARY, wid)
    assert status == "pending_approval"
    
    from app.impact import calculate_impact
    impact = calculate_impact(wid)
    assert impact["workflow_id"] == wid
    assert impact["status"] == "pending_approval"
    assert impact["budget"] == 10000000.0
    assert impact["final_cost"] > 0
    assert impact["savings"] >= 0
    assert impact["suppliers_evaluated"] > 0
    assert impact["duration_ms"] > 0
    assert impact["automated_steps"] > 0

def test_impact_endpoint():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    
    wid = "wf_impact_endpoint_test"
    _run(PRIMARY, wid)
    
    response = client.get(f"/api/workflows/{wid}/impact")
    assert response.status_code == 200
    impact = response.json()
    assert impact["workflow_id"] == wid
    assert impact["final_cost"] > 0
'''
with open('tests/test_scenarios.py', 'a') as f:
    f.write(code)
