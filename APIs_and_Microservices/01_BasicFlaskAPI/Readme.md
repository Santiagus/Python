# FlaskAPI 

This project start from previous one adding a new API for kitchen orders that will be implemented using flask-smorest.

Flask-smorest is a REST API framework built on top of Flask and marshmallow


## Initial Setup

**1. Create project folder** \
```mkdir 01_BasicFlaskAPI```

**2. Create virtual environment** \
```python -m venv .venv```

**3. Copy ../00_BasicFastAPI/orders folder** \
```cp -r ../00_BasicFastAPI/orders/ .```

**4. Activate virtual environment** \
```. .venv/bin/activate```

**5.Install dependencies** 
- From scratch: \
 ```pip install uvicorn FastAPI flask-smorest``` 
- From requirements.txt \
```pip install -r requirements.txt```

**6. Save requirements** \
```pip freeze > requirements.txt```

**7. Check app is working** \
Run : ```uvicorn orders.app:app --reload``` \
Check: http://127.0.0.1:8000/docs