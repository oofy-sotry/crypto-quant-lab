from django.urls import reverse


def test_root_redirects_to_dashboard(client, settings):
    settings.DASHBOARD_URL = "https://dashboard.example.com"

    response = client.get(reverse("root"))

    assert response.status_code == 302
    assert response["Location"] == "https://dashboard.example.com"


def test_root_is_404_without_dashboard_url(client, settings):
    settings.DASHBOARD_URL = ""

    response = client.get(reverse("root"))

    assert response.status_code == 404
