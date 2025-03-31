# Dockerfile to build the image for dab_nginx service

FROM mirror.gcr.io/library/nginx:1.27

COPY nginx.conf /etc/nginx/conf.d/default.conf

# Modify the default Nginx configuration to allow it to run as a non-root user
# This follows Nginx Docker Hub instructions: https://hub.docker.com/_/nginx
# By default, Nginx writes its PID file to /var/run/nginx.pid, which is a restricted location.
# We change it to /tmp/nginx.pid so that it can be accessed by a non-root user.
RUN sed -i -E '/^user\s+nginx;/d' /etc/nginx/nginx.conf && \
    sed -i -E 's|pid\s+/var/run/nginx.pid;|pid        /tmp/nginx.pid;|' /etc/nginx/nginx.conf && \
    sed -i '/http {/a \
    client_body_temp_path /tmp/client_temp;\n\
    proxy_temp_path       /tmp/proxy_temp;\n\
    fastcgi_temp_path     /tmp/fastcgi_temp;\n\
    uwsgi_temp_path       /tmp/uwsgi_temp;\n\
    scgi_temp_path        /tmp/scgi_temp;' /etc/nginx/nginx.conf

USER nginx