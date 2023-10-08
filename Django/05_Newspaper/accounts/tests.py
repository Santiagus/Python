from django.test import TestCase
from http import HTTPStatus

# Create your tests here.
from django.contrib.auth import get_user_model
from django.urls import reverse


class SingUpTetst(TestCase):
    def test_url_exist_at_the_correct_location_signupview(self):
        response = self.client.get("/accounts/signup/")
        self.assertEqual(response.status_code, 200)

    def test_signup_view_name(self):
        response = self.client.get(reverse("signup"))
        with self.subTest(msg="signup name test"):
            self.assertEqual(response.status_code, HTTPStatus.OK)
        with self.subTest(msg="signup templated used"):
            self.assertTemplateUsed(response, "registration/signup.html")

    def test_signup_form(self):
        response = self.client.post(
            reverse("signup"),
            {
                "username": "testuser",
                "email": "testuser@email.com",
                "age": "34",
                "password1": "testpass123",
                "password2": "testpass123",
            },
        )
        with self.subTest(msg="signup form status_code"):
            self.assertEqual(response.status_code, HTTPStatus.FOUND)
        with self.subTest(msg="signup form object count 1"):
            self.assertEqual(get_user_model().objects.all().count(), 1)
        with self.subTest(msg="signup form username check"):
            # self.assertEqual(get_user_model().objects.all()[0].username, "testuser")
            self.assertEqual(
                get_user_model().objects.all()[0].get_username(), "testuser"
            )
        with self.subTest(msg="signup form email check"):
            # self.assertEqual(get_user_model().objects.all()[0].email, "testuser@email.com")
            self.assertEqual(
                get_user_model().objects.all()[0].get_email_field_name(),
                "testuser@email.com",
            )
