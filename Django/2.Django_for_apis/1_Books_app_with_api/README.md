Based on Django for APIs by William S. Vincent

## Django Books app
1. Base setup 
    - Install python if needed ([python downloads)](https://www.python.org/downloads/macos/)
    - Upgrade pip: `python3 -m pip install --upgrade pip`
    - Create venv : `python3 -m venv .venv`
    - Activate virtural environment : `.venv/bin/activate`
    - Install packages in requirements.txt: `pip install -r requirements.txt`
 
2. Create django project
    `django-admin startproject django_project .`

3. Sync database : `python3 manage.py migrate`
4. Run server: `python3 manage.py runserver`

5. Update *django/project/settings.py*

    ```python
    INSTALLED_APPS = [
        ...
        # Local
        "books.apps.BooksConfig", # new
    ]
    ```

6. Add *Book model* :
    *books/models.py*
    ```python
        # books/models.py
        from django.db import models
        class Book(models.Model):
            title = models.CharField(max_length=250)
            subtitle = models.CharField(max_length=250)
            author = models.CharField(max_length=100)
            isbn = models.CharField(max_length=13)

        def __str__(self):
            return self.title
    ```

7. Following the model creation, create a database model specifying the app name
`python manage.py makemigrations books`

8. Apply to the existing database
`python manage.py migrate`

9. Create user/s to enter data 
`python manage.py createsuperuser`

10. Register book model into books/admin.py
    ```python
    from .models import Bookpython manage.py createsuperuser

    admin.site.register(Book)
    ```

11. Update books/vies.py to modify the way content is displayed
    ```python
    from .models import Book

    class BookListView(ListView):
            model = Book
            template_name = "book_list.html"
    ```

12. Create the template in default path : 
    ```django
    <!-- books/templates/books/book_list.html -->
    <h1>All books</h1>
    {% for book in book_list %}
    <ul>
        <li>Title: {{ book.title }}</li>
        <li>Subtitle: {{ book.subtitle }}</li>
        <li>Author: {{ book.author }}</li>
        <li>ISBN: {{ book.isbn }}</li>
    </ul>
    {% endfor %}
    ```
    Alternative is create a project level `templates` folder and update `django_project/settings.py` to point here

13. Update urls so : 
    
    ```python
    # django_project/urls.py
    from django.contrib import admin
    from django.urls import path, include # new
    urlpatterns = [
        path("admin/", admin.site.urls),
        path("", include("books.urls")), # new
    ]
    ```
    
    ```python
    # books/urls.py
    from django.urls import path
    from .views import BookListView
    urlpatterns = [
        path("", BookListView.as_view(), name="home"),
    ]   
    ```

14. Tests

    ```python
    # books/tests.py
    from django.test import TestCase
    from django.urls import reverse
    from .models import Book

    class BookTests(TestCase):
        @classmethod
        def setUpTestData(cls):
            cls.book = Book.objects.create(
            title="A good title",
            subtitle="An excellent subtitle",
            author="Tom Christie",
            isbn="1234567890123",
        )

        def test_book_content(self):
            self.assertEqual(self.book.title, "A good title")
            self.assertEqual(self.book.subtitle, "An excellent subtitle")
            self.assertEqual(self.book.author, "Tom Christie")
            self.assertEqual(self.book.isbn, "1234567890123")

        def test_book_listview(self):
            response = self.client.get(reverse("home"))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "excellent subtitle")
            self.assertTemplateUsed(response, "books/book_list.html")
    ```
    Run test: `python manage.py test`

    ## Library API

    1. Add REST framework and APIs app to project settings
        ```python
        #django_project/settings.py
        INSTALLED_APPS = [
            ...
            # 3rd party
            "rest_framework",
            # local
            "apis.apps.ApisConfig"
        ]
        ```
    2. Create APIs app

        `python manage.py startapp apis`

    3. Add api route
        ```python
        # django_project/urls.py
        from django.contrib import admin
        from django.urls import path, include

        urlpatterns = [
            path("admin/", admin.site.urls),
            path("api/", include("apis.urls")), # new
            path("", include("books.urls")),
        ]
        ```

    4. Add Serializers
        ```python
        # apis/serializers.py
        from rest_framework import serializers
        from books.models import Book

        class BookSerializer(serializers.ModelSerializer):
            class Meta:
                model = Book
                fields = ("title" "subtitle", "author", "isbn")
        ```

    5. Add views using hte previous serializer
        ```python
        # apis/views.py
        from rest_framework import generics
        from books.models import Book
        from .serializers import BookSerializer
        
        class BookAPIView(generics.ListAPIView):
            queryset = Book.objects.all()
            serializer_class = BookSerializer
        ```