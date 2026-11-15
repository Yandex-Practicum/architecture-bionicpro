FROM golang:1.22-alpine AS build

WORKDIR /src
COPY go.mod go.sum main.go ./
RUN CGO_ENABLED=0 go build -o /yandex-id-bridge .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /yandex-id-bridge /yandex-id-bridge
EXPOSE 8090
ENTRYPOINT ["/yandex-id-bridge"]
