FROM python:3.9-slim
RUN mkdir -p /orders/orders
WORKDIR /orders
RUN pip install -U pip && pip install pipenv
# COPY Pipfile Pipfile.lock /orders/
COPY requirements.txt /orders/
#RUN pipenv install --dev --system --deploy
RUN pip install -r requirements.txt
COPY orders/repository /orders/orders/repository/
COPY migrations /orders/migrations
COPY alembic.ini /orders/alembic.ini
ENV PYTHONPATH=/orders
CMD ["alembic", "upgrade", "heads"]