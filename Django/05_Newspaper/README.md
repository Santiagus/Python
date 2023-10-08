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

- Add test url signup view
    ```python
    from django.test import TestCase
    from django.contrib.auth import get_user_model
    from django.urls import reverse

    class SingUpTetst(TestCase):
        def test_url_exist_at_the_correct_location_signupview(self):
            response = self.client.get("/accounts/signup/")
            self.assertEqual(response.status_code, 200)
    ```
