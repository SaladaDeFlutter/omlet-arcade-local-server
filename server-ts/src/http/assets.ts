import fs from 'node:fs';
import http from 'node:http';

import { CONFIG } from '../config';

export function startAssetServer(): http.Server {
  const server = http.createServer((request, response) => {
    const url = request.url ?? '/';
    let filePath = '';
    if (url.startsWith('/cover')) {
      filePath = CONFIG.coverPath;
    } else if (url.startsWith('/avatar') || url.startsWith('/blob/')) {
      filePath = CONFIG.avatarPath;
    }
    if (!filePath) {
      response.writeHead(404);
      response.end();
      return;
    }
    fs.readFile(filePath, (error, data) => {
      if (error) {
        response.writeHead(404);
        response.end();
        return;
      }
      response.writeHead(200, {
        'Content-Type': 'image/png',
        'Content-Length': data.length,
      });
      response.end(data);
    });
  });
  server.listen(CONFIG.assetPort, '0.0.0.0', () => {
    console.log(
      `${new Date().toISOString()} asset HTTP server listening on 0.0.0.0:${CONFIG.assetPort}`,
    );
    console.log(
      `${new Date().toISOString()} avatar URL: ${CONFIG.avatarHttpUrl}`,
    );
  });
  return server;
}
