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