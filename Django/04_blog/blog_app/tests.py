import unittest
from parameterized import parameterized
from django.test import TestCase
from django.urls import reverse
from termcolor import colored

# from django.contrib.auth import get_user_model
from django.contrib.auth.models import User

from .models import Post

# Create your tests here.


class BlogTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create_user(
            username="testuser", email="test@email.com", password="secret"
        )
        cls.post = Post.objects.create(
            title="A good title",
            body="Nice body content",
            author=cls.user,
        )

    def test_post_model(self):
        with self.subTest(msg="post title check"):
            self.assertEqual(self.post.title, "A good title")
        with self.subTest(msg="post body check"):
            self.assertEqual(self.post.body, "Nice body content")
        with self.subTest(msg="post author name check"):
            self.assertEqual(self.post.author.username, "testuser")
        with self.subTest(msg="post __str__ equal title check"):
            self.assertEqual(str(self.post), "A good title")
        with self.subTest(msg="post url check"):
            self.assertEqual(self.post.get_absolute_url(), "/post/1/")

    @parameterized.expand(
        [
            ("/", 200),
            ("/post/1/", 200),
            ("post/100000", 404),
        ]
    )
    def test_url_exist_at_correct_location(self, url, expected_status_code):
        response = self.client.get(url)
        self.assertEqual(
            response.status_code,
            expected_status_code,
            colored(
                f"Expected status code {expected_status_code} but got {response.status_code} for '{url}'",
                "red",
            ),
        )

    @parameterized.expand(
        [
            ("post_listview", "home", 200, "Nice body content", "home.html", False),
            (
                "post_detailview",
                "post_detail",
                200,
                "A good title",
                "post_detail.html",
                True,
            ),
            # Add more test cases as needed
        ]
    )
    def test_views(
        self,
        test_name,
        url_name,
        expected_status_code,
        content_check,
        template_check,
        use_pk,
    ):
        if use_pk:
            url = reverse(url_name, kwargs={"pk": self.post.pk})
        else:
            url = reverse(url_name)

        response = self.client.get(url)

        with self.subTest(msg=f"{test_name} status code check"):
            status_msg = f"Expected status code {expected_status_code} but got {response.status_code}"
            self.assertEqual(
                response.status_code, expected_status_code, colored(status_msg, "red")
            )

        with self.subTest(msg=f"{test_name} content check"):
            content_msg = f"{test_name} - Content check failed"
            self.assertContains(
                response, content_check, msg_prefix=colored(content_msg, "red")
            )

        with self.subTest(msg=f"{test_name} template used"):
            template_msg = f"{test_name} - Template check failed"
            self.assertTemplateUsed(
                response, template_check, msg_prefix=colored(template_msg, "red")
            )
