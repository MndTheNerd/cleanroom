# Egress proxy: the builder's only route out. Allows HTTPS CONNECT to hosts in allowlist.txt, denies everything else.
FROM alpine:3.20
RUN apk add --no-cache squid
COPY squid.conf /etc/squid/squid.conf
COPY allowlist.txt /etc/squid/allowlist.txt
# Run unprivileged from the start: no setuid step, so compose can drop every capability.
USER squid
EXPOSE 3128
CMD ["squid", "-N", "-f", "/etc/squid/squid.conf"]
