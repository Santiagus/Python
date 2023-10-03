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
    ```django
    from django.contrib import admin
    from .models import Post

    admin.site.register(Post)
    ```