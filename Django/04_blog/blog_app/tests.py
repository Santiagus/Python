from django.test import TestCase
from django.urls import reverse

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

    def test_url_exists_at_correct_location_listview(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_url_exists_at_correct_location_detailview(self):
        response = self.client.get("/post/1/")
        self.assertEqual(response.status_code, 200)

    def test_post_listview(self):
        response = self.client.get(reverse("home"))
        with self.subTest(msg="post status code check"):
            self.assertEqual(response.status_code, 200)
        with self.subTest(msg="post content check"):
            self.assertContains(response, "Nice body content")
        with self.subTest(msg="post template used"):
            self.assertTemplateUsed(response, "home.html")

    def test_post_detailview(self):
        response = self.client.get(reverse("post_detail", kwargs={"pk": self.post.pk}))
        no_response = self.client.get("post/100000")
        with self.subTest(msg="no response"):
            self.assertEqual(no_response.status_code, 404)
        with self.subTest(msg="post response"):
            self.assertEqual(response.status_code, 200)
        with self.subTest(msg="post content check"):
            self.assertContains(response, "A good title")
        with self.subTest(msg="post content check"):
            self.assertTemplateUsed(response, "post_detail.html")
