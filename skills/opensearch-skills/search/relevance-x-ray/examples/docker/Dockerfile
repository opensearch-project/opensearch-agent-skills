FROM opensearchproject/opensearch:3.8.0

USER root

COPY --chown=opensearch:opensearch fixtures/ /usr/share/opensearch/demo/fixtures/
COPY --chown=opensearch:opensearch seed-demo.sh /usr/share/opensearch/demo/seed-demo.sh
COPY --chown=opensearch:opensearch docker/demo-entrypoint.sh /usr/share/opensearch/demo/demo-entrypoint.sh

RUN chmod 0755 \
    /usr/share/opensearch/demo/seed-demo.sh \
    /usr/share/opensearch/demo/demo-entrypoint.sh

USER opensearch

ENV DEMO_FIXTURES_DIR=/usr/share/opensearch/demo/fixtures
ENV OPENSEARCH_URL=http://127.0.0.1:9200

ENTRYPOINT ["/usr/share/opensearch/demo/demo-entrypoint.sh"]
