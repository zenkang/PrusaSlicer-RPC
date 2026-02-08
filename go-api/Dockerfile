FROM golang:1.25.7-alpine
WORKDIR /app
COPY . .
RUN go mod download
RUN go build -o main .
CMD ["./main"]