FROM golang:1.22-alpine AS build

WORKDIR /src
COPY go.mod go.sum main.go ./
RUN CGO_ENABLED=0 go build -o /bionicpro-auth .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /bionicpro-auth /bionicpro-auth
EXPOSE 8000
ENTRYPOINT ["/bionicpro-auth"]
