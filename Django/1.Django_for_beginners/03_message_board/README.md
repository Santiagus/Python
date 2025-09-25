## Message Board app
- Initial Set Up
    ```bash
    $ mkdir message-board
    $ cd message-board
    $ python3 -m venv .venv
    $ . .venv/bin/activate
    (.venv) $ python3 -m pip install django~=4.0.0
    (.venv) $ django-admin startproject message_board .
    (.venv) $ python3 manage.py startapp posts
    ```

- Update *django_project/settings.py*
    ```django
    INSTALLED_APPS = ["posts.apps.PostsConfig", # new]
    ```

- Create initial database with default settings
    ```bash
    $ python manage.py migrate
    ```

- Create database model
    ```python
    from django.db import models

    class Post(models.Model):
        text = models.TextField()
    ```
- Create migrations file
    ```bash
    (.venv) > python manage.py makemigrations posts
    ```
- Build database (which execute instructions in migrations file)
    ```bash
    (.venv) > python manage.py migrate
    ```

- Create superuser who can log in
    ```bash
    $ python manage.py createsuperuser
    ```
- Login at http://127.0.0.1:8000/admin

- Register model to make it appear in admin panel
    ```python
    from django.contrib import admin
    from .models import Post

    admin.site.register(Post)
    ```

- Update model to show other than 'Post object(id)` in admin panel.
    ```python
    from django.db import models

    class Post(models.Model):
        text = models.TextField()

        def __str__(self):
            return self.text[:50]
    ```

- Create view in *posts/views.py* to list post in database.

    ListView automatically returns a context variable called \<model>_list.

    ```python
    from django.views.generic import ListView
    from .models import Post

    class HomePageView(ListView):
        model = Post
        template_name = "home.html"
    ```
- Create templates folder and include the path in *message_board/settings.py*
    ```python
    TEMPLATES = [{"DIRS": [BASE_DIR / "templates"],}]
    ```
- Create *template/home.html*
    ```django
    <h1>Message board homepage</h1>
    <ul>
        {% for post in post_list %}
            <li>{{ post.text }}</li>
        {% endfor %}
    </ul>
    ```

- Create test in *posts/test.py*
    <details>
        <summary>posts/test.py</summary>

    ```python
        from django.test import TestCase 
        from django.urls import reverse
        from .models import Post

        class PostTest(TestCase):
            @classmethod
            def setUpTestData(cls) -> None:
                cls.post = Post.objects.create(text="This is a test!")

            def test_model_content(self):
                self.assertEqual(self.post.text, "This is a test!")

            def test_url_exist_at_correct_location(self):
                response = self.client.get("/")
                self.assertEqual(response.status_code, 200)

            def test_homepage(self):
                response = self.client.get(reverse("home"))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "home.html")
                self.assertContains(response, "This is a test!")    
    ```
    </details>