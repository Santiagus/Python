#BLOG APP   
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