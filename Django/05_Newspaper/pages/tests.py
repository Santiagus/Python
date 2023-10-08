from django.test import SimpleTestCase
from django.urls import reverse
from http import HTTPStatus


# Create your tests here.
class HomePageTest(SimpleTestCase):
    def test_url_exists_at_correct_location_homepageview(self):
        response = self.client.get("home.tml")
        self.assertEqual(response.status_code, HTTPStatus.OK)
