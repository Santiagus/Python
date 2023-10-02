Sample Project with Home and about pages implementation

# Initial Set up
- Create venv, activate and install Django in it
```
$python -m venv .venv
$. .venv/bin/activate
(.venv)$ python -m pip install django~=4.0.0
```
- Create Django project and app
```
(.venv)$ django-admin startproject homeabout .
(.venv)$ python manage.py startapp pages
```

- Add app to project's settings and set templates path
*homeabout/settings.py*
```
INSTALLED_APPS = ["pages.apps.PagesConfig", # new]
TEMPLATES = [{"DIRS": [BASE_DIR / "templates"],},]
```

# Create Views
- Create *templates/home.html*
- Add class view *pages/views.py*
```
from django.views.generic import TemplateView

class HomePageView(TemplateView):
    template_name = "home.html" 
```
- Add path to pages urls in project/urls.py
```
from django.urls import path, include
urlpatterns = [path("", include("pages.urls")),]
```
- Create pages/urls.py
```
from django.urls import path
from .views import HomePageView
urlpatterns = [path("", HomePageView.as_view(), name="home"),]
```

- Same procedure for about page.

*pages/view.py*
```
class AboutPageView(TemplateView): # new
    template_name = "about.html"
```
*pages/urls.py*
```
urlpatterns = [path("about/", AboutPageView.as_view(), name="about",]
```
*templages/about.html*
```
<h1>About page</h1>
```
# Extending Templates
  A *base.html* can be defined to be used and extended in the defined pages as follows:
  ```
  <header>
    <a href="{% url 'home' %}">Home</a> |
    <a href="{% url 'about' %}">About</a>
  </header>
  {% block content %} {% endblock content %}
  ```
  Then add it to the home & about pages:
  ```
    {% extends "base.html" %}
    {% block content%}
    <h1>About page</h1>
    {% endblock content%}
  ```

# Add Tests
*pages/tests.py*
```
from django.test import SimpleTestCase

class HomepageTests(SimpleTestCase):
    def test_url_exists_at_correct_location(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

class AboutpageTests(SimpleTestCase):
    def test_url_exists_at_correct_location(self):
        response = self.client.get("/about/")
        self.assertEqual(response.status_code, 200)
```
# Run Tests
```
$ python manage.py test
```