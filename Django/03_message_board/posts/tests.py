from django.test import TestCase

from .models import Post


class PostTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.post = Post.objects.create(text="This is a test!")

    def test_model_content(self):
        self.assertEqual(self.post.text, "This is a test!")
