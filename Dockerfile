FROM python:3.10-slim

LABEL maintainer="Owner <you@example.com>"

# Tạo thư mục chứa mã nguồn
WORKDIR /opt/odoo

# Cài đặt các gói phụ thuộc hệ thống
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    libxml2-dev \
    libxslt1-dev \
    libldap2-dev \
    libsasl2-dev \
    libjpeg-dev \
    libffi-dev \
    libssl-dev \
    git \
    curl \
    npm \
    nodejs \
    python3-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Cài đặt pip dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Sao chép mã nguồn
COPY . .

# Tạo volume để lưu file tạm
RUN mkdir -p /opt/odoo/data
VOLUME ["/opt/odoo/data"]

CMD ["python", "odoo-bin", "-c", "odoo.cfg"]
