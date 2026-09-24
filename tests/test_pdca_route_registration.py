def test_pdca_readonly_route_is_registered_without_removing_existing_routes(monkeypatch):
    monkeypatch.setenv('DY_API_TEST_MODE', '1')
    from dy_api.main import create_app

    paths = create_app().openapi()['paths']
    assert '/api/v1/admin/ranking-source-evidence' in paths
    assert '/api/v1/auth/me' in paths
    assert '/api/v1/admin/pdca-source-evidence' in paths
