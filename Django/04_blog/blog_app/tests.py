from django.test import TestCase

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
