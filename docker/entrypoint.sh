#!/usr/bin/env bash
set -euo pipefail

domain="hawihandyman.com"
email="${CERTBOT_EMAIL:?CERTBOT_EMAIL must be set}"
certificate="/etc/letsencrypt/live/${domain}/fullchain.pem"

if [[ ! -s "$certificate" ]]; then
    certbot certonly \
        --non-interactive \
        --agree-tos \
        --email "$email" \
        --dns-route53 \
        --cert-name "$domain" \
        -d "$domain" \
        -d "www.${domain}"
fi

renew_certificates() {
    while sleep 12h; do
        certbot renew --quiet --deploy-hook "httpd -k graceful"
    done
}

renew_certificates &
renewal_pid=$!
httpd -DFOREGROUND &
httpd_pid=$!

shutdown() {
    kill -TERM "$httpd_pid" "$renewal_pid" 2>/dev/null || true
    wait "$httpd_pid" 2>/dev/null || true
    wait "$renewal_pid" 2>/dev/null || true
}
trap shutdown TERM INT

wait "$httpd_pid"
