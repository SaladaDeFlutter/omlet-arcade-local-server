export const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS accounts (
  account_id TEXT PRIMARY KEY,
  client_pub TEXT UNIQUE,
  omlet_id TEXT NOT NULL,
  scopes_json TEXT NOT NULL DEFAULT '[]',
  created_ms INTEGER NOT NULL,
  has_email INTEGER NOT NULL DEFAULT 1,
  has_password INTEGER NOT NULL DEFAULT 1,
  account_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS posts (
  post_id TEXT PRIMARY KEY,
  author_account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  created_ms INTEGER NOT NULL,
  legacy_like_count INTEGER NOT NULL DEFAULT 0,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS posts_created_idx ON posts(created_ms DESC);
CREATE INDEX IF NOT EXISTS posts_author_idx ON posts(author_account_id);

CREATE TABLE IF NOT EXISTS post_likes (
  post_id TEXT NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
  account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
  created_ms INTEGER NOT NULL,
  PRIMARY KEY (post_id, account_id)
);

CREATE TABLE IF NOT EXISTS comments (
  comment_id TEXT PRIMARY KEY,
  post_id TEXT NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
  author_account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  created_ms INTEGER NOT NULL,
  client_id TEXT
);
CREATE INDEX IF NOT EXISTS comments_post_idx ON comments(post_id, created_ms);
CREATE INDEX IF NOT EXISTS comments_author_idx ON comments(author_account_id);

CREATE TABLE IF NOT EXISTS communities (
  community_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  icon TEXT NOT NULL DEFAULT '',
  cover TEXT NOT NULL DEFAULT '',
  owner_account_id TEXT REFERENCES accounts(account_id) ON DELETE SET NULL,
  created_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS communities_created_idx ON communities(created_ms DESC);

CREATE TABLE IF NOT EXISTS community_members (
  community_id TEXT NOT NULL REFERENCES communities(community_id) ON DELETE CASCADE,
  account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'member',
  joined_ms INTEGER NOT NULL,
  PRIMARY KEY (community_id, account_id)
);
CREATE INDEX IF NOT EXISTS community_members_account_idx ON community_members(account_id);

CREATE TABLE IF NOT EXISTS channels (
  channel_id TEXT PRIMARY KEY,
  community_id TEXT NOT NULL REFERENCES communities(community_id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  key_b64 TEXT NOT NULL,
  created_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS channels_community_idx ON channels(community_id);

CREATE TABLE IF NOT EXISTS channel_messages (
  message_id TEXT PRIMARY KEY,
  channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE CASCADE,
  author_account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  created_us INTEGER NOT NULL,
  client_id TEXT
);
CREATE INDEX IF NOT EXISTS channel_messages_channel_idx ON channel_messages(channel_id, created_us);
CREATE INDEX IF NOT EXISTS channel_messages_author_idx ON channel_messages(author_account_id);
`;
