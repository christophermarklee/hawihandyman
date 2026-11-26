FROM fedora:45

RUN dnf -y install \
      httpd \
      mod_ssl \
      certbot \
      python3-certbot-dns-route53 \
      curl \
    && dnf clean all \
    && rm -rf /var/cache/dnf \
    && rm -f /etc/httpd/conf.d/ssl.conf

COPY docker/httpd/hawihandyman.conf /etc/httpd/conf.d/hawihandyman.conf
COPY docker/entrypoint.sh /usr/local/bin/hawihandyman-entrypoint
COPY site/ /var/www/html/

RUN chmod 0755 /usr/local/bin/hawihandyman-entrypoint \
    && mkdir -p /var/lib/letsencrypt /etc/letsencrypt

EXPOSE 80 443

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD curl --fail --silent --show-error https://localhost/ --insecure >/dev/null || exit 1

ENTRYPOINT ["/usr/local/bin/hawihandyman-entrypoint"]
