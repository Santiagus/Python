Based on Chapter 5: Todo API in Django for APIS by Williams S.Vincent


## Initial Setup

Create venv and install needed libs
```
> py -m venv .venv
> .venv/bin/activate
(.venv)> python -m pip install django~=4.0.0 
```

New project/app
```
(.venv) > django-admin startproject django_project .
(.venv) > python manage.py startapp todos
(.venv) > python manage.py migrate
```

Add app to INSTALED_APPS
```python
# django_project/settings.py
INSTALLED_APPS = [
    ...
    # local
    "todos.apps.TodosConfig"
]
```