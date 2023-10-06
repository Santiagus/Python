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
