## Initial Set Up

```bash
$ mkdir message-board
$ cd message-board
$ python3 -m venv .venv
$ . .venv/bin/activate
(.venv) $ python3 -m pip install django~=4.0.0
(.venv) $ django-admin startproject message_board .
(.venv) $ python3 manage.py startapp posts
```

## Update settings
django_project/settings.py
```
INSTALLED_APPS = ["posts.apps.PostsConfig", # new]
```