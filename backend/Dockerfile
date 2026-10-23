FROM python:3.12.4

WORKDIR /app


# Python dependencies
RUN pip install --no-cache-dir      \
    "flask==3.0.3"                  \
    "bitcoinlib==0.6.13"            \
    "bech32==1.2.0"                 \
    "fastecdsa==3.0.1"


# Copy the source code
COPY . .

EXPOSE 8000
CMD ["python3", "-u", "main.py"]
