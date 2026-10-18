import websocket from '@fastify/websocket';
import Fastify from 'fastify';

import { CONFIG } from './config';
import { initializeDatabase } from './db/client';
import { repositories } from './db/repositories';
import { startAssetServer } from './http/assets';
import { longdanHandler, type SocketState } from './protocol/handler';
import { SERVER_PUBLIC_B64 } from './protocol/crypto';

async function main(): Promise<void> {
  initializeDatabase();
  startAssetServer();

  const app = Fastify({
    logger: { level: process.env.LOG_LEVEL ?? 'info' },
    bodyLimit: 1024 * 1024 * 32,
  });

  await app.register(websocket, {
    options: {
      maxPayload: 0,
      perMessageDeflate: false,
    },
  });

  const websocketRoute = (
    socket: import('ws').WebSocket,
    request: import('fastify').FastifyRequest,
  ): void => {
    const state: SocketState = {};
    const path = request.url;
    console.log(`${new Date().toISOString()} CONNECT ${path}`);

    socket.on('message', (raw) => {
      void (async () => {
        try {
          const response = await longdanHandler.handle(
            Buffer.isBuffer(raw) ? raw : Buffer.from(raw as ArrayBuffer),
            state,
            path,
          );
          if (response) socket.send(response);
        } catch (error) {
          console.log(
            `${new Date().toISOString()} HANDLER_ERROR ${path} ${String(error)}`,
          );
        }
      })();
    });

    socket.on('close', () => {
      console.log(`${new Date().toISOString()} DISCONNECT ${path}`);
    });
    socket.on('error', (error) => {
      console.log(
        `${new Date().toISOString()} SOCKET_ERROR ${path} ${String(error)}`,
      );
    });
  };

  app.get('/device', { websocket: true }, websocketRoute);
  app.get('/readonlydevice', { websocket: true }, websocketRoute);

  await app.listen({ host: '0.0.0.0', port: CONFIG.port });
  console.log(
    `${new Date().toISOString()} Omlet local server listening on 0.0.0.0:${CONFIG.port}`,
  );
  console.log(
    `${new Date().toISOString()} server public key: ${SERVER_PUBLIC_B64}`,
  );
  console.log(`${new Date().toISOString()} database: ${CONFIG.dbPath}`);
  console.log(
    `${new Date().toISOString()} accounts loaded: ${repositories.countAccounts()}`,
  );
  console.log(
    `${new Date().toISOString()} posts loaded: ${repositories.listPosts(1000).length}`,
  );
  console.log(
    `${new Date().toISOString()} communities loaded: ${repositories.listCommunities(undefined, 1000).length}`,
  );
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
