FROM apify/actor-python:3.13

COPY requirements.txt ./

RUN echo "Python version:" \
    && python --version \
    && echo "Installing dependencies:" \
    && pip install -U pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt \
    && echo "All installed dependencies:" \
    && pip freeze

COPY . ./

CMD ["python", "-m", "src"]
