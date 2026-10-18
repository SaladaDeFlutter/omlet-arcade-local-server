import { defineConfig } from 'drizzle-kit';
import { CONFIG } from './src/config';

export default defineConfig({
  schema: './src/db/schema.ts',
  out: './drizzle',
  dialect: 'sqlite',
  dbCredentials: { url: CONFIG.dbPath },
});
