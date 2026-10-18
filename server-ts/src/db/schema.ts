import { index, integer, primaryKey, sqliteTable, text } from 'drizzle-orm/sqlite-core';

export const accounts = sqliteTable(
  'accounts',
  {
    accountId: text('account_id').primaryKey(),
    clientPub: text('client_pub').unique(),
    omletId: text('omlet_id').notNull(),
    scopesJson: text('scopes_json').notNull().default('[]'),
    createdMs: integer('created_ms').notNull(),
    hasEmail: integer('has_email').notNull().default(1),
    hasPassword: integer('has_password').notNull().default(1),
    accountJson: text('account_json').notNull().default('{}'),
    bio: text('bio').notNull().default(''),
    avatarUrl: text('avatar_url').notNull().default(''),
    backgroundUrl: text('background_url').notNull().default(''),
  },
  (table) => [index('accounts_created_idx').on(table.createdMs)],
);

export const posts = sqliteTable(
  'posts',
  {
    postId: text('post_id').primaryKey(),
    authorAccountId: text('author_account_id')
      .notNull()
      .references(() => accounts.accountId, { onDelete: 'cascade' }),
    title: text('title').notNull(),
    description: text('description').notNull().default(''),
    createdMs: integer('created_ms').notNull(),
    legacyLikeCount: integer('legacy_like_count').notNull().default(0),
    metadataJson: text('metadata_json').notNull().default('{}'),
  },
  (table) => [
    index('posts_created_idx').on(table.createdMs),
    index('posts_author_idx').on(table.authorAccountId),
  ],
);

export const postLikes = sqliteTable(
  'post_likes',
  {
    postId: text('post_id')
      .notNull()
      .references(() => posts.postId, { onDelete: 'cascade' }),
    accountId: text('account_id')
      .notNull()
      .references(() => accounts.accountId, { onDelete: 'cascade' }),
    createdMs: integer('created_ms').notNull(),
  },
  (table) => [primaryKey({ columns: [table.postId, table.accountId] })],
);

export const comments = sqliteTable(
  'comments',
  {
    commentId: text('comment_id').primaryKey(),
    postId: text('post_id')
      .notNull()
      .references(() => posts.postId, { onDelete: 'cascade' }),
    authorAccountId: text('author_account_id')
      .notNull()
      .references(() => accounts.accountId, { onDelete: 'cascade' }),
    text: text('text').notNull(),
    createdMs: integer('created_ms').notNull(),
    clientId: text('client_id'),
  },
  (table) => [
    index('comments_post_idx').on(table.postId, table.createdMs),
    index('comments_author_idx').on(table.authorAccountId),
  ],
);

export const communities = sqliteTable(
  'communities',
  {
    communityId: text('community_id').primaryKey(),
    name: text('name').notNull(),
    description: text('description').notNull().default(''),
    icon: text('icon').notNull().default(''),
    cover: text('cover').notNull().default(''),
    ownerAccountId: text('owner_account_id').references(
      () => accounts.accountId,
      { onDelete: 'set null' },
    ),
    createdMs: integer('created_ms').notNull(),
  },
  (table) => [index('communities_created_idx').on(table.createdMs)],
);

export const communityMembers = sqliteTable(
  'community_members',
  {
    communityId: text('community_id')
      .notNull()
      .references(() => communities.communityId, { onDelete: 'cascade' }),
    accountId: text('account_id')
      .notNull()
      .references(() => accounts.accountId, { onDelete: 'cascade' }),
    role: text('role').notNull().default('member'),
    joinedMs: integer('joined_ms').notNull(),
  },
  (table) => [
    primaryKey({ columns: [table.communityId, table.accountId] }),
    index('community_members_account_idx').on(table.accountId),
  ],
);

export const channels = sqliteTable(
  'channels',
  {
    channelId: text('channel_id').primaryKey(),
    communityId: text('community_id')
      .notNull()
      .references(() => communities.communityId, { onDelete: 'cascade' }),
    name: text('name').notNull(),
    description: text('description').notNull().default(''),
    keyB64: text('key_b64').notNull(),
    createdMs: integer('created_ms').notNull(),
  },
  (table) => [index('channels_community_idx').on(table.communityId)],
);

export const channelMessages = sqliteTable(
  'channel_messages',
  {
    messageId: text('message_id').primaryKey(),
    channelId: text('channel_id')
      .notNull()
      .references(() => channels.channelId, { onDelete: 'cascade' }),
    authorAccountId: text('author_account_id')
      .notNull()
      .references(() => accounts.accountId, { onDelete: 'cascade' }),
    text: text('text').notNull(),
    createdUs: integer('created_us').notNull(),
    clientId: text('client_id'),
  },
  (table) => [
    index('channel_messages_channel_idx').on(
      table.channelId,
      table.createdUs,
    ),
    index('channel_messages_author_idx').on(table.authorAccountId),
  ],
);

export type AccountRow = typeof accounts.$inferSelect;
export type PostRow = typeof posts.$inferSelect;
export type CommentRow = typeof comments.$inferSelect;
export type CommunityRow = typeof communities.$inferSelect;
export type ChannelRow = typeof channels.$inferSelect;
export type ChannelMessageRow = typeof channelMessages.$inferSelect;
