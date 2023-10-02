# Django Quick Start

- Create Project Folder: 
```
$ mkdir my_project
```
- Create a dedicated virtual environment 
```
$ python3 -m venv <MYVENV>
```
- Activate virtual environment ()
```
$ . .venv/bin/activate
```
- Install desired Django version
```
(.venv)$ python -m pip install django~=4.0.0
```
- Create a new Django Project
```
(.venv)$ django-admin startproject django_project .
```
- Run Django internal web server
```
(.venv)$ python3 manage.py runserver
```
- Verify is running at http://127.0.0.1:8000/
- Stops it with CONTROL-C
- Deactivate virtual environment
```
(.venv)$ deactivate
```
- Create App
```
(.venv)$ python manage.py startapp <APPNAME>
```
- Check created directory
```
(.venv)$ tree
├── APPNAME
│ ├── __init__.py
│ ├── admin.py
│ ├── apps.py
│ ├── migrations
│ │ └── __init__.py
│ ├── models.py
│ ├── tests.py
│ └── views.py
```
**admin.py  :** configuration file for the built-in Django Admin app.

**apps.py   :** configuration file for the app itself.

**migrations/ :** keeps track of models.py file changes.

**models.py :** database models which Django translates into database tables.

**tests.py  :** app-specific tests.

**views.py  :** request/response logic for our web app.

- Save installed packages in venv
```
(.venv)$ pip freeze > requirements.txt
```
- To install the packages listed in the requirements.txt file use
```
$python -m pip install -r requirements.txt
```
