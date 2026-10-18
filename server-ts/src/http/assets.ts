import fs from 'node:fs';
import http from 'node:http';

import { CONFIG } from '../config';
import { hexFromSegment, readBlob, writeBlob } from './blobs';

function contentTypeFor(data: Buffer): string {
  if (data.length >= 8 && data.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) {
    return 'image/png';
  }
  if (data.length >= 3 && data[0] === 0xff && data[1] === 0xd8 && data[2] === 0xff) {
    return 'image/jpeg';
  }
  if (data.length >= 6 && data.subarray(0, 6).toString('ascii').startsWith('GIF8')) {
    return 'image/gif';
  }
  if (
    data.length >= 12 &&
    data.subarray(0, 4).toString('ascii') === 'RIFF' &&
    data.subarray(8, 12).toString('ascii') === 'WEBP'
  ) {
    return 'image/webp';
  }
  return 'application/octet-stream';
}

function sendBuffer(response: http.ServerResponse, data: Buffer): void {
  response.writeHead(200, {
    'Content-Type': contentTypeFor(data),
    'Content-Length': data.length,
    'Cache-Control': 'public, max-age=31536000',
  });
  response.end(data);
}

function sendFile(response: http.ServerResponse, filePath: string): void {
  fs.readFile(filePath, (error, data) => {
    if (error) {
      response.writeHead(404);
      response.end();
      return;
    }
    sendBuffer(response, data);
  });
}

function readBody(request: http.IncomingMessage): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    request.on('data', (chunk: Buffer) => chunks.push(chunk));
    request.on('end', () => resolve(Buffer.concat(chunks)));
    request.on('error', reject);
  });
}

function serveBlobOrFallback(
  response: http.ServerResponse,
  segment: string,
  fallbackPath: string,
): void {
  const hex = hexFromSegment(segment);
  const data = hex ? readBlob(hex) : null;
  if (data) {
    sendBuffer(response, data);
    return;
  }
  sendFile(response, fallbackPath);
}

export function startAssetServer(): http.Server {
  const server = http.createServer((request, response) => {
    const pathName = (request.url ?? '/').split('?')[0];
    const segments = pathName.split('/').filter((part) => part.length > 0);
    const method = request.method ?? 'GET';

    if ((method === 'PUT' || method === 'POST') && segments[0] === 'blob') {
      readBody(request)
        .then((body) => {
          if (body.length === 0) {
            response.writeHead(400);
            response.end();
            return;
          }
          const hex = writeBlob(body);
          console.log(
            `${new Date().toISOString()} BLOB_STORED ${hex} ${body.length} bytes`,
          );
          response.writeHead(200, { 'Content-Type': 'application/json' });
          response.end(JSON.stringify({ ok: true, hash: hex }));
        })
        .catch(() => {
          response.writeHead(500);
          response.end();
        });
      return;
    }

    if (segments.length === 2 && segments[0] === 'blob') {
      serveBlobOrFallback(response, segments[1], CONFIG.avatarPath);
      return;
    }
    if (segments.length === 2 && segments[0] === 'avatar') {
      serveBlobOrFallback(response, segments[1], CONFIG.avatarPath);
      return;
    }

    if (pathName.startsWith('/cover')) {
      sendFile(response, CONFIG.coverPath);
      return;
    }
    if (pathName.startsWith('/avatar') || pathName.startsWith('/blob/')) {
      sendFile(response, CONFIG.avatarPath);
      return;
    }

    response.writeHead(404);
    response.end();
  });

  server.listen(CONFIG.assetPort, '0.0.0.0', () => {
    console.log(
      `${new Date().toISOString()} asset HTTP server listening on 0.0.0.0:${CONFIG.assetPort}`,
    );
    console.log(
      `${new Date().toISOString()} avatar URL: ${CONFIG.avatarHttpUrl}`,
    );
    console.log(`${new Date().toISOString()} blob base: ${CONFIG.blobBase}`);
  });
  return server;
}
