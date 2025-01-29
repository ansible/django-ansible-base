FROM quay.io/centos/centos:stream9

RUN sed -i '/^\[crb\]$/,/^enabled=0$/ s/enabled=0/enabled=1/' /etc/yum.repos.d/centos.repo
RUN dnf -y install \
    python3.11 \
    python3.11-pip \
    python3.11-devel \
    gcc \
    openldap-devel \
    xmlsec1 \
    xmlsec1-openssl \
    xmlsec1-devel \
    libtool-ltdl-devel \
    libpq-devel \
    libpq \
    postgresql

# Create /etc/ansible-automation-platform/testapp folder
RUN mkdir -p /etc/ansible-automation-platform/testapp
# add settings.yaml to /etc/ansible-automation-platform/
COPY test_app/example_files/*.yaml /etc/ansible-automation-platform/testapp/

RUN python3.11 -m venv /venv

COPY requirements/requirements_all.txt /tmp/requirements_all.txt
RUN /venv/bin/pip install -r /tmp/requirements_all.txt

COPY requirements/requirements_dev.txt /tmp/requirements_dev.txt
RUN /venv/bin/pip install -r /tmp/requirements_dev.txt
