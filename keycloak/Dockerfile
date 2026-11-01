FROM quay.io/keycloak/keycloak:21.1 AS keycloak-base
FROM eclipse-temurin:17-jdk AS provider-build
WORKDIR /build
COPY --from=keycloak-base /opt/keycloak/lib/lib/main/ /deps/
COPY yandex-provider/src/ ./src/
RUN mkdir classes && javac -cp '/deps/*' -d classes src/main/java/bionicpro/*.java \
    && cp -R src/main/resources/. classes/ \
    && jar --create --file yandex-provider.jar -C classes .
FROM keycloak-base
COPY --from=provider-build --chown=1000:0 /build/yandex-provider.jar /opt/keycloak/providers/
RUN /opt/keycloak/bin/kc.sh build --db=postgres
