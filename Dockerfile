FROM fedora:45

RUN dnf -y install \
      httpd \
      mod_ssl \
      certbot \
      python3-certbot-dns-route53 \
      curl \
      python3 \
      python3-pip \
    && dnf clean all \
    && rm -rf /var/cache/dnf \
    && rm -f /etc/httpd/conf.d/ssl.conf

COPY requirements.txt /opt/haleclock/requirements.txt
RUN python3 -m venv /opt/haleclock/venv \
    && /opt/haleclock/venv/bin/pip install --no-cache-dir -r /opt/haleclock/requirements.txt

COPY docker/httpd/hawihandyman.conf /etc/httpd/conf.d/hawihandyman.conf
COPY docker/entrypoint.sh /usr/local/bin/hawihandyman-entrypoint
COPY site/ /var/www/html/
COPY app/ /opt/haleclock/app/

RUN chmod 0755 /usr/local/bin/hawihandyman-entrypoint \
    && mkdir -p /var/lib/letsencrypt /etc/letsencrypt /var/lib/haleclock

EXPOSE 80 443

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD curl --fail --silent --show-error https://localhost/ --insecure >/dev/null || exit 1

ENTRYPOINT ["/usr/local/bin/hawihandyman-entrypoint"]
