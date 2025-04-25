FROM python:3.9

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_APP=app
ENV FLASK_ENV=development
ENV FLASK_RUN_PORT=8080
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

ENTRYPOINT ["flask", "run", "--host=0.0.0.0","--port=8080"]