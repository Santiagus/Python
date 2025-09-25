from django.test import SimpleTestCase
from django.urls import reverse
from http import HTTPStatus


# Create your tests here.
class HomePageTest(SimpleTestCase):
    def test_url_exists_at_correct_location_homepageview(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, HTTPStatus.OK)

    def test_homepage_view(self):
        response = self.client.get(reverse("home"))
        with self.subTest(msg="homepage name resolution check"):
            self.assertEqual(response.status_code, HTTPStatus.OK)
        with self.subTest(msg="homepage template used check"):
            self.assertTemplateUsed(response, "home.html")
        with self.subTest(msg="homepage contain check"):
            self.assertContains(response, "Home")
