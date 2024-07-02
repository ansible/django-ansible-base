#!/bin/bash -x

if [[ ! -f /etc/nginx/ssl/selfsigned.key ]]; then
    openssl req \
        -x509 \
        -nodes \
        -days 365 \
        -newkey rsa:2048 \
        -keyout /etc/nginx/ssl/selfsigned.key \
        -out /etc/nginx/ssl/selfsigned.crt \
        -subj "/CN=localhost"
fi

nginx -g "daemon off;"
