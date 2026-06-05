#!/usr/bin/env node
import net from "node:net";

const args = process.argv.slice(2);
let host = "127.0.0.1";
const ports = [];

for (let index = 0; index < args.length; index += 1) {
  const arg = args[index];
  if (arg === "--host") {
    host = args[index + 1] ?? host;
    index += 1;
    continue;
  }
  ports.push(parsePort(arg));
}

if (!ports.length) {
  ports.push(8000);
}

const occupied = [];
for (const port of ports) {
  if (!(await isPortAvailable(host, port))) {
    occupied.push(port);
  }
}

if (occupied.length) {
  console.error(`Port(s) already in use on ${host}: ${occupied.join(", ")}`);
  console.error(
    "Stop the existing listener, run `make kill`, or override BACKEND_PORT.",
  );
  process.exitCode = 1;
} else {
  console.log(`Port(s) available on ${host}: ${ports.join(", ")}`);
}

function parsePort(value) {
  const port = Number.parseInt(value ?? "", 10);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(
      `Port must be an integer between 1 and 65535, got ${value}`,
    );
  }
  return port;
}

function isPortAvailable(host, port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.listen({ host, port }, () => {
      server.close(() => resolve(true));
    });
  });
}
