# BLOG APP

- Initial Setup
    ```bash
    $ mkdir 04_blog
    $ cd 04_blog
    $ python3 -m venv .venv
    $ . .venv/bin/activate
    (.venv) $ django-admin startproject blog .
    (.venv) $ python3 manage.py startapp blog_app
    (.venv) $ python3 manage.py migrate
    ```
- Update settings
    ```python
    TEMPLATES = [{"DIRS": [BASE_DIR / "templates"],},]
    INSTALLED_APPS = ["blog_app.apps.BlogAppConfig",]
    ```
- Create models
    <details> 
    <summary>blog_app/models.py</summary>
    
    ```python
    from django.db import models
    from django.urls import reverse

    class Post(models.Model):
        title = models.CharField(max_length=200)
        author = models.ForeignKey("auth.User",on_delete=models.CASCADE,)
        body = models.TextField()

        def __str__(self):
            return self.title

        def get_absolute_url(self):
            return reverse("post_detail", kwargs={"pk": self.pk})
    ```
    </details>

- Build database
    ```bash
    (.venv) $ python3 manage.py makemigrations blog_app
    (.venv) $ python3 manage.py migrate
    ```
- Create superuser
    ```bash
    (.venv) $ python3 manage.py createsuperuser
    ```

- Register model
    ```python
    from django.contrib import admin
    from .models import Post

    admin.site.register(Post)
    ```

- Create view
    ```python
    from django.views.generic import ListView
    from .models import Post

    class BlogListView(ListView):
        model = Post
        template_name = "home.html"
    ```

- Create *blog_app/urls.py* adding the created view
    ```python
    from django.urls import path
    from .views import BlogListView

    urlpatterns = [path("", BlogListView.as_view()),]
    ```
- Add app in *blog/urls.py*
    ```python
    from django.contrib import admin
    from django.urls import path, include

    urlpatterns = [
        path("admin/", admin.site.urls),
        path("", include("blog_app.urls")),
    ]
    ```

- Create *templates* folder and add :
    <details>
    <summary>base.html</summary>

    ```html
    <html> 
        <head><title>Django blog</title></head>
        <body>
        <header>
            <h1><a href="{% url 'home' %}">Django blog</a></h1>
        </header>
        <div>
            {% block content %}
            {% endblock content %}
        </div>
        </body>
    </html>
    ```
    </details>

    <details>
    <summary>home.html</summary>

    ```html
    {% extends "base.html" %}
    {% block content %}
    {% for post in post_list %}
    <div class="post-entry">
    <h2><a href="">{{ post.title }}</a></h2>
    <p>{{ post.body }}</p>
    </div>
    {% endfor %}
    {% endblock content %}
    ```
    </details>

- Create *static/css* folder and add *base.css*:
    <details>
    <summary>base.css</summary>

    ```css
    body {
        font-family: 'Source Sans Pro', sans-serif;
        font-size: 18px;
    }

    header {
        border-bottom: 1px solid #999;
        margin-bottom: 2rem;
        display: flex;
    }

    header h1 a {
        color: red;
        text-decoration: none;
    }

    .nav-left {
        margin-right: auto;
    }

    .nav-right {
        display: flex;
        padding-top: 2rem;
    }

    .post-entry {
        margin-bottom: 2rem;
    }

    .post-entry h2 {
        margin: 0.5rem 0;
    }

    .post-entry h2 a,
    .post-entry h2 a:visited {
        color: blue;
        text-decoration: none;
    }

    .post-entry p {
        margin: 0;
        font-weight: 400;
    }

    .post-entry h2 a:hover {
        color: red;
    }
    ```
    </details>

- Add detail view in *blog/views.py*:
    ```python
    from django.views.generic import ListView, DetailView

    class BlogDetailView(DetailView):
        model = Post
        template_name = "post_detail.html"
    ```
- Add *template/post_detail.html*
    ```django
    {% extends "base.html" %}
    {% block content %}
    <div class="post-entry">
        <h2>{{ post.title }}</h2>
        <p>{{ post.body }}</p>
    </div>
    {% endblock content %}
    ```

## Testing

- Create test class *BlogTest* with *setUpTestData* method:

    ```python
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
    ```

- Create post model tests:
    ```python
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
    ```

- Create url exists tests:
    ```python
    @parameterized.expand(
    [
        ("/", 200),
        ("/post/1/", 200),
        ("post/100000", 404),
    ])
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
    ```

- Create views test:
    ```python
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
    ])
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

    ```

## Add Form for adding new posts
- Create view in *blog/views.py*
    ```python
    from django.views.generic.edit import CreateView # new
    class BlogCreateView(CreateView): # new
        model = Post
        template_name = "post_new.html"
        fields = ["title", "author", "body"]
    ```

- Update *base.html* adding a link to the form page:
    ```html
    <div class="nav-right">
        <a href="{% url 'post_new' %}">+ New Blog Post</a>
    </div>
    ```
- Add url in *blog/urls.py*:
    ```python
    from django.urls import path
    from .views import BlogListView, BlogDetailView, BlogCreateView # new
    urlpatterns = [path("post/new/", BlogCreateView.as_view(), name="post_new"),]
    ```
- Create *post_new.html* in *templates*:

    *NOTE:* **csrf_token** (Cross Site Request Forgery protection)
    ```django
    {% extends "base.html" %}
    {% block content %}
    <h1>New post</h1>
    <form action="" method="post">{% csrf_token %}
    {{ form.as_p }}
    <input type="submit" value="Save">
    </form>
    {% endblock content %}
    ```

## Add Edit post page
- Create view in *blog/views.py*
    ```python
    class BlogUpdateView(CreateView):
        model = Post
        template_name = "post_edit.html"
        fields = ["title", "body"]
    ```

- Update *post_detail.html* adding a link to the edit form page:
    ```html
    <a href="{% url 'post_edit' post.pk %}"> + Edit Blog Post </a>
    ```
- Add url in *blog/urls.py*:
    ```python
    path("post/<int:pk>/edit/", BlogUpdateView.as_view(), name="post_edit"),
    ```

- Create *post_edit.html* in *templates*:
    ```django
    {% extends "base.html" %}
    {% block content %}
    <h1>Edit post</h1>
    <form action="" method="post"> {% csrf_token %}
        {{ form.as_p }}
        <input type="submit" value="Update">
    </form>

    {% endblock content %}
    ```
*NOTE:* Edit post form should be autofilled with the post info, if not stop the server and run again.

## Add delete post page
- Create view in *blog/views.py*
    ```python
    from django.urls import reverse_lazy

    class BlogDeleteView(DeleteView):
        model = Post
        template_name = "post_delete.html"
        success_url = reverse_lazy("home")
    ```

- Update *post_detail.html* adding a link to the delete post page:
    ```html
    <p><a href="{% url 'post_delete' post.pk %}">+ Delete Blog Post</a></p>
    ```
- Add url in *blog/urls.py*:
    ```python
    path("post/<int:pk>/delete/", BlogDeleteView.as_view(), name="post_delete"),
    ```

- Create *post_delete.html* in *templates*:
    ```django
    {% extends "base.html" %}
    {% block content %}
    <h1>Delete post</h1>
    <form action="" method="post">{% csrf_token %}
        <p>Are you sure you want to delete "{{ post.title }}"?</p>
        <input type="submit" value="Confirm">
    </form>
    {% endblock content %}
    ```
