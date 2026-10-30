FROM maven:3.9.9-eclipse-temurin-21 AS build
WORKDIR /build
COPY pom.xml .
RUN mvn -q -B dependency:go-offline
COPY src src
RUN mvn -q -B -DskipTests package

FROM eclipse-temurin:21.0.5_11-jre-jammy
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=build /build/target/legacy-stub-0.1.0.jar app.jar
USER app
ENV JAVA_OPTS="-Xmx384m"
CMD ["sh", "-c", "exec java $JAVA_OPTS -jar app.jar"]
