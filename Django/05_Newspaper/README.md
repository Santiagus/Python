## Initial Setup
```bash
$ mkdir 05_Newspaper
$ cd 05_Newspaper
$ python -m venv .venv
$ . .venv/bin/activate
(.venv) $ python -m pip install django~=4.0.0
(.venv) $ python -m pip install whitenoise==5.3.0
(.venv) $ python -m pip install parameterized
(.venv) $ python -m pip install termcolor
(.venv) $ django-admin startproject django_project .
(.venv) $ python manage.py startapp accounts
(.venv) $ pip freeze > requirements.txt
```
## Create Custom User Model
- Add accounts app to *django_project/settings.py*
    ```python
    INSTALLED_APPS = ["accounts.apps.AccountsConfig",]
    AUTH_USER_MODEL = "accounts.CustomUser"
    ```
- Update *accounts/models.py*
    ```python
    from django.contrib.auth.models import AbstractUser
    from django.db import models

    class CustomUser(AbstractUser):
        age = models.PositiveIntegerField(null=True, blank=True)
    ```

- Create *accounts/forms.py* to update built-in for create/update users
    ```python
    from django.contrib.auth.forms import UserCreationForm, UserChangeForm
    from .models import CustomUser

    class CustomUserCreationForm(UserCreationForm):
        class Meta(UserCreationForm):
            model = CustomUser
            fields = UserCreationForm.Meta.fields + ("age",)

    class CustomUserChangeForm(UserChangeForm):
        class Meta:
            model = CustomUser
            fields = UserChangeForm.Meta.fields

    ```

- Update *accounts/admin.py* extending UserAdmin with custom model
    ```python
    from django.contrib import admin
    from django.contrib.auth.admin import UserAdmin
    from .forms import CustomUserCreationForm, CustomUserChangeForm
    from .models import CustomUser


    class CustomUserAdmin(UserAdmin):
        add_form = CustomUserCreationForm
        form = CustomUserChangeForm
        model = CustomUser
        list_display = [
            "email",
            "username",
            "age",
            "is_staff",
        ]
        fieldsets = UserAdmin.fieldsets + ((None, {"fields": ("age",)}),)
        add_fieldsets = UserAdmin.add_fieldsets + ((None, {"fields": ("age",)}),)


    admin.site.register(CustomUser, CustomUserAdmin)
    ```
    
- Create a new database that uses the custom user model
    ```bash
    (.venv) > python manage.py makemigrations accounts
    (.venv) > python manage.py migrate
    ```

- Create superuser account
    ```bash
    (.venv) > python manage.py createsuperuser
    ```
- Run server and check in *http://127.0.0.1:8000/admin* if *age* field added appear
    ```bash
    (.venv) > python manage.py runserver
    ```

## User Authentication
- Create *templates/registration* directory as that’s where
Django will look for templates related to log in and sign up.
    ```bash
    (.venv) $ mk dir templates
    (.venv) $ mk dir templates/registration
    ```

- Updates *django_project/settings/py* adding templates dir and redir page when login/logout
    ```python
    TEMPLATES = [{"DIRS": [BASE_DIR / "templates"], }]
    LOGIN_REDIRECT_URL = "home"
    LOGOUT_REDIRECT_URL = "home"
    ```

- Create templates:

    <details>
    <summary> template/base.html </summary>

    ```django
    <!DOCTYPE html>
    <html>
        <head>
        <meta charset="utf-8">
        <title>{% block title %}Newspaper App{% endblock title %}</title>
    </head>
    <body>
        <main>
        {% block content %}
        {% endblock content %}
        </main>
    </body>
    </html>
    ```
    </details>

    <details> <summary> template/home.html </summary>

    ```django
    {% extends "base.html" %}

    {% block title %}Home{% endblock title %}

    {% block content %}
    {% if user.is_authenticated %}
        Hi {{ user.username }}!
        <p><a href="{% url 'logout' %}">Log Out</a></p>
    {% else %}
        <p>You are not logged in</p>
        <a href="{% url 'login' %}">Log In</a> |
        <a href="{% url 'signup' %}">Sign Up</a>
    {% endif %}
    {% endblock content %}
    ```
    </details>

    <details> <summary> template/registration/login.html </summary>

    ```django
    {% extends "base.html" %}

    {% block title %}Log In{% endblock title %}

    {% block content %}
        <h2>Log In</h2>
        <form method="post">{% csrf_token %}
            {{ form.as_p }}
            <button type="submit">Log In</button>
        </form>
    {% endblock content %}
    ```
    </details>


    <details> <summary> template/registration/signup.html </summary>

    ```django
    {% extends "base.html" %}

    {% block title %}Sign Up{% endblock title %}

    {% block content %}
    <h2>Sign Up</h2>
    <form method="post">{% csrf_token %}
        {{ form.as_p }}
        <button type="submit">Sign Up</button>
    </form>
    {% endblock content %}
    ```
    </details>


- Create *accounts/views.py*
    ```python
    from django.urls import reverse_lazy
    from django.views.generic import CreateView
    from .forms import CustomUserCreationForm


    class SignUpView(CreateView):
        form_class = CustomUserCreationForm
        success_url = reverse_lazy("login")
        template_name = "registration/signup.html"
    ```

- Create *accounts/urls.py*
    ```python
    from django.urls import path
    from .views import SignUpView

    urlpatterns = [path("signup/", SignUpView.as_view(), name="signup"),]
    ```
- Update *django_project/urls.py*
    ```python
    from django.contrib import admin
    from django.urls import path, include
    from django.views.generic.base import TemplateView

    urlpatterns = [
        path("admin/", admin.site.urls),
        path("accounts/", include("accounts.urls")),
        path("accounts/", include("django.contrib.auth.urls")),
        path("", TemplateView.as_view(template_name="home.html"),
        name="home"),]
    ```

- Update *accounts/forms.py* to allow set *age* value
    <details> <summary>accounts/forms.py</summary>
    ```python
    from django.contrib.auth.forms import UserCreationForm, UserChangeForm
    from .models import CustomUser

    class CustomUserCreationForm(UserCreationForm):
        class Meta(UserCreationForm):
            model = CustomUser
            fields = ("username", "email", "age")

    class CustomUserChangeForm(UserChangeForm):
        class Meta:
            model = CustomUser
            fields = ("username", "email", "age")
    ```
    </details>


## Tests

- Add test signup view
    <details> <summary> accounts/tests.py</summary>

    ```python
    from django.test import TestCase
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
            self.assertEqual(
                get_user_model().objects.all()[0].email, "testuser@email.com"
            )

        with self.subTest(msg="signup form age check"):
            self.assertEqual(get_user_model().objects.all()[0].age, 34)
    ```
    </details>


## Add pages app
- Create *pages* app:
    ```bash
    (.venv) > python manage.py startapp pages
    ```

- Add app config to *django_project/settings/py*:
    ```python
    INSTALLED_APPS = ["pages.apps.PagesConfig",]
    ```
- Update *django_project/urls.py*:
    ```python
    from django.contrib import admin
    from django.urls import path, include

    urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("pages.urls")), # new
    ```

- Add *pages/urls.py*:
    ```python
    from django.urls import path
    from .views import HomePageView

    urlpatterns = [path("", HomePageView.as_view(), name="home"),]
    ```

- Add *pages/views.py*:
    ```python
    from django.views.generic import TemplateView

    class HomePageView(TemplateView):
        template_name = "home.html"
    ```
- Add *pages/test.py*:
    ```python
    from django.test import SimpleTestCase
    from django.urls import reverse
    from http import HTTPStatus

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
    ```

## Bootstrap

- Add bootstrap ["Starter template info"](https://getbootstrap.com/docs/5.1/getting-started/introduction/#quick-start) :

    <details><summary>base.html</summary>

    ```django    
        <meta name="viewport" content="width=device-width,
    initial-scale=1, shrink-to-fit=no">
        <!-- Bootstrap CSS -->    
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-1BmE4kWBq78iYhFldvKuhfTAU6auU8tT94WrHftjDbrCEXSU1oBoqyl2QvZ6jIW3" crossorigin="anonymous">
    ...
        <!-- Bootstrap JavaScript Bundle -->
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.min.js" integrity="sha384-QJHtvGhmr9XOIpI6YVutG+2QOK9T+ZnN4kzFN1RtK3zEFEIsxhlmWl5/YESvpZ13" crossorigin="anonymous"></script>
    </body>
    </html>
    ```
    </details>

- Update *templates/base.html*:

    <details><summary>base.html</summary>

    ```html
    <!DOCTYPE html>
    <html>
        <head>
        <meta charset="utf-8">
        <title>{% block title %}Newspaper App{% endblock title %}</title>
        <meta name="viewport" content="width=device-width,
    initial-scale=1, shrink-to-fit=no">
        <!-- Bootstrap CSS -->    
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-1BmE4kWBq78iYhFldvKuhfTAU6auU8tT94WrHftjDbrCEXSU1oBoqyl2QvZ6jIW3" crossorigin="anonymous">
    </head>
    <body>
    <div class="container">
    <header class="p-3 mb-3 border-bottom">
        <div class="container">
        <div class="d-flex flex-wrap align-items-center justify-content-center justify-content-lg-start">
        <a class="navbar-brand" href="{% url 'home' %}">Newspaper</a>
        <ul class="nav col-12 col-lg-auto me-lg-auto mb-2 justify-content-center mb-md-0">
        {% if user.is_authenticated %}
            <li><a href="#" class="nav-link px-2 link-dark">+ New</a></li>
            </ul>
            <div class="dropdown text-end">
            <a href="#" class="d-block link-dark text-decoration-none dropdown-toggle" id="dropdownUser1" data-bs-toggle="dropdown" aria-expanded="false">
            {{ user.username }}
            </a>
            <ul class="dropdown-menu text-small" aria-labelledby="dropdownUser1">
                <li><a class="dropdown-item" href="{% url 'password_change'%}">
                    Change password</a></li>
                <li><a class="dropdown-item" href="{% url 'logout' %}">Log Out</a></li>
            </ul>
            </div>
        {% else %}
            </ul>
            <div class="text-end">
            <a href="{% url 'login' %}" class="btn btn-outline-primary me-2">
            Log In</a>
            <a href="{% url 'signup' %}" class="btn btn-primary">Sign Up</a>
            </div>
        {% endif %}
        </div>
        </div>
    </header>

    <main>
        {% block content %}
        {% endblock content %}
    </main>
    <!-- Bootstrap JavaScript Bundle -->
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.min.js" integrity="sha384-QJHtvGhmr9XOIpI6YVutG+2QOK9T+ZnN4kzFN1RtK3zEFEIsxhlmWl5/YESvpZ13" crossorigin="anonymous"></script>

    </body>
    </html>
    ```
    </details>

- Update *registration.login.html* button style:
    ```html
    <button class="btn btn-success ml-2" type="submit">Log In</button>
    ```

## Restyle the help_text in forms
- Install crispy
    ```bash
    (.venv) > python -m pip install django-crispy-forms==1.13.0
    (.venv) > python -m pip install crispy-bootstrap5==0.6
    ```
- Add app in *django_project/settings.py*:
    ```python
    INSTALLED_APPS = [
    "django.contrib....
    # 3rd Party
    "crispy_forms", # new
    "crispy_bootstrap5", # new
    # Local
    "accounts.apps.AccountsConfig",
    "pages.apps.PagesConfig",
    ]
    CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
    CRISPY_TEMPLATE_PACK = "bootstrap5"
    ```
- Update *registration/signup.html* to *crispy* style:
    ```django
    {% extends "base.html" %}
    {% load crispy_forms_tags %}
    {% block title %}Sign Up{% endblock title %}

    {% block content %}
    <h2>Sign Up</h2>
    <form method="post">{% csrf_token %}
        {{ form|crispy }}
        <button class="btn btn-success" type="submit">Sign Up</button>
    </form>
    {% endblock content %}
    ```

- Update *registration/login.html* to *crispy* style:
    ```django
    {% extends "base.html" %}
    {% load crispy_forms_tags %}
    {% block title %}Log In{% endblock title %}

    {% block content %}
        <h2>Log In</h2>
        <form method="post">{% csrf_token %}
            {{ form|crispy }}
            <button class="btn btn-success ml-2" type="submit">Log In</button>
        </form>
    {% endblock content %}
    ```
## Customizing Password Change

- Create *registration/password_change_form.html*:
    ```html
    {% extends "base.html" %}
    {% load crispy_forms_tags %}
    {% block title %}Password Change{% endblock title %}

    {% block content %}
    <h1>Password change</h1>
    <p>Please enter your old password, for security's sake, and then enter
    your new password twice so we can verify you typed it in correctly.</p>
    <form method="POST">{% csrf_token %}
        {{ form|crispy }}
        <input class="btn btn-success" type="submit" value="Change my password">
    </form>
    {% endblock content %}
    ```

- Create *registration/password_change_done.html*:
    ```html
    {% extends "base.html" %}
    {% block title %}Password Change Successful{% endblock title %}
    {% block content %}
    <h1>Password change successful</h1>
    <p>Your password was changed.</p>
    {% endblock content %}
    ```