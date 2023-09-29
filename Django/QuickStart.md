# Django Quick Start

- Create Project Folder: 
```
$ mkdir my_project
```
- Create a dedicated virtual environment 
```
$ python3 -m venv <MYVENV>
```
- Activate venv
```
$ . .venv/bin/activate
```
- Install desired Django version
```
(.venv) > python -m pip install django~=4.0.0
```
- Create a new Django Project
```
(.venv) > django-admin startproject django_project .
```
- Run Django internal web server
```
(.venv) > python3 manage.py runserver
```
- Verify is running at http://127.0.0.1:8000/
- Stops it with CONTROL-C
- Deactivate virtual environment
```
(.venv) > deactivate
```
