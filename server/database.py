import base64
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager

LOG = logging.getLogger("omlet.db")

SCHEMA_VERSION = 1

SCHEMA = """
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
CREATE INDEX IF NOT EXISTS channel_messages_channel_idx
    ON channel_messages(channel_id, created_us);
CREATE INDEX IF NOT EXISTS channel_messages_author_idx
    ON channel_messages(author_account_id);
"""


def _b64e(value):
    return base64.b64encode(value).decode("ascii")


def _b64d(value):
    return base64.b64decode(value)


def _decode_text(raw):
    try:
        decoded = _b64d(raw).decode("utf-8", "replace")
    except Exception:
        return ""
    try:
        payload = json.loads(decoded)
        if isinstance(payload, dict):
            return str(payload.get("text", ""))
    except Exception:
        pass
    return decoded


class Database:
    def __init__(self, path, default_icon="", default_cover=""):
        self.path = path
        self.default_icon = default_icon
        self.default_cover = default_cover
        self.lock = threading.RLock()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        try:
            yield conn
        finally:
            conn.close()

    def initialize(self):
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            conn.commit()

    @staticmethod
    def _account_from_row(row):
        if row is None:
            return None
        record = dict(row)
        record["scopes"] = json.loads(record.pop("scopes_json") or "[]")
        record["z"] = json.loads(record.pop("account_json") or "{}")
        record["has_email"] = bool(record.get("has_email", 1))
        record["has_password"] = bool(record.get("has_password", 1))
        return record

    def find_account(self, client_pub=None, account_id=None):
        with self.connect() as conn:
            row = None
            if account_id:
                row = conn.execute(
                    "SELECT * FROM accounts WHERE account_id=?",
                    (account_id,),
                ).fetchone()
            if row is None and client_pub:
                row = conn.execute(
                    "SELECT * FROM accounts WHERE client_pub=?",
                    (client_pub,),
                ).fetchone()
        return self._account_from_row(row)

    def all_accounts(self):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM accounts ORDER BY created_ms"
            ).fetchall()
        return [self._account_from_row(row) for row in rows]

    def count_accounts(self):
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]

    def upsert_account(self, record):
        client_pub = record.get("client_pub") or None
        account_id = record["account_id"]
        scopes = json.dumps(record.get("scopes", []))
        account_json = json.dumps(record.get("z", {}), ensure_ascii=False)
        created_ms = int(record.get("created_ms") or time.time() * 1000)
        has_email = 1 if record.get("has_email", True) else 0
        has_password = 1 if record.get("has_password", True) else 0
        with self.connect() as conn, conn:
            existing = conn.execute(
                "SELECT account_id FROM accounts "
                "WHERE account_id=? OR (client_pub IS NOT NULL AND client_pub=?)",
                (account_id, client_pub),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE accounts
                    SET client_pub=?, omlet_id=?, scopes_json=?,
                        created_ms=?, has_email=?, has_password=?, account_json=?
                    WHERE account_id=?
                    """,
                    (
                        client_pub,
                        record.get("omlet_id", "omletplayer"),
                        scopes,
                        created_ms,
                        has_email,
                        has_password,
                        account_json,
                        existing["account_id"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO accounts(
                        account_id, client_pub, omlet_id, scopes_json,
                        created_ms, has_email, has_password, account_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        account_id,
                        client_pub,
                        record.get("omlet_id", "omletplayer"),
                        scopes,
                        created_ms,
                        has_email,
                        has_password,
                        account_json,
                    ),
                )
        return self.find_account(account_id=account_id)

    def ensure_account(self, account_id, omlet_id="omletplayer"):
        record = self.find_account(account_id=account_id)
        if record:
            return record
        now = int(time.time() * 1000)
        record = {
            "account_id": account_id,
            "client_pub": None,
            "omlet_id": omlet_id,
            "scopes": ["PublicProfile", "Arcade"],
            "created_ms": now,
            "has_email": True,
            "has_password": True,
            "z": {
                "a": {
                    "a": account_id,
                    "c": "ONE",
                    "d": "GUEST",
                    "i": [{"p": omlet_id, "t": "omlet"}],
                    "p": omlet_id,
                    "s": now,
                },
                "S": ["PublicProfile", "Arcade"],
                "i": _b64e(b""),
                "e": True,
                "p": False,
            },
        }
        return self.upsert_account(record)

    def list_posts(self, limit=50):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM posts ORDER BY created_ms DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_post(self, post_id):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM posts WHERE post_id=?", (post_id,)
            ).fetchone()
        return dict(row) if row else None

    def ensure_post(
        self,
        post_id,
        author_account_id,
        title,
        description="",
        created_ms=None,
        metadata=None,
    ):
        with self.connect() as conn, conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO posts(
                    post_id, author_account_id, title, description,
                    created_ms, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    post_id,
                    author_account_id,
                    title,
                    description,
                    int(created_ms or time.time() * 1000),
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
        return self.get_post(post_id)

    def count_posts_by_author(self, account_id):
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM posts WHERE author_account_id=?",
                (account_id,),
            ).fetchone()[0]

    def set_like(self, post_id, account_id, liked):
        with self.connect() as conn, conn:
            if liked:
                conn.execute(
                    "INSERT OR IGNORE INTO post_likes(post_id, account_id, created_ms) "
                    "VALUES (?, ?, ?)",
                    (post_id, account_id, int(time.time() * 1000)),
                )
            else:
                conn.execute(
                    "DELETE FROM post_likes WHERE post_id=? AND account_id=?",
                    (post_id, account_id),
                )
        return self.count_likes(post_id)

    def is_liked(self, post_id, account_id):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM post_likes WHERE post_id=? AND account_id=?",
                (post_id, account_id),
            ).fetchone()
        return row is not None

    def count_likes(self, post_id):
        with self.connect() as conn:
            legacy = conn.execute(
                "SELECT legacy_like_count FROM posts WHERE post_id=?",
                (post_id,),
            ).fetchone()
            if legacy is None:
                return 0
            count = conn.execute(
                "SELECT COUNT(*) FROM post_likes WHERE post_id=?",
                (post_id,),
            ).fetchone()[0]
        return int(legacy["legacy_like_count"]) + int(count)

    def count_comments(self, post_id):
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM comments WHERE post_id=?", (post_id,)
            ).fetchone()[0]

    def add_comment(self, post_id, author_account_id, text, client_id=None):
        comment_id = client_id or _b64e(os.urandom(8))
        with self.connect() as conn, conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO comments(
                    comment_id, post_id, author_account_id, text,
                    created_ms, client_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    comment_id,
                    post_id,
                    author_account_id,
                    text,
                    int(time.time() * 1000),
                    client_id,
                ),
            )
            row = conn.execute(
                "SELECT * FROM comments WHERE comment_id=?", (comment_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_comments(self, post_id):
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT c.*, a.omlet_id AS author_omlet_id
                FROM comments c
                JOIN accounts a ON a.account_id = c.author_account_id
                WHERE c.post_id=?
                ORDER BY c.created_ms
                """,
                (post_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_community(
        self,
        community_id,
        name,
        description="",
        icon="",
        cover="",
        owner_account_id=None,
        created_ms=None,
    ):
        with self.connect() as conn, conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO communities(
                    community_id, name, description, icon, cover,
                    owner_account_id, created_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    community_id,
                    name,
                    description,
                    icon or self.default_icon,
                    cover or self.default_cover,
                    owner_account_id,
                    int(created_ms or time.time() * 1000),
                ),
            )
        return self.get_community(community_id)

    def create_community(self, name, description, icon, cover, owner_account_id):
        community_id = uuid.uuid4().hex
        community = self.insert_community(
            community_id,
            name,
            description,
            icon or self.default_icon,
            cover or self.default_cover,
            owner_account_id,
        )
        if owner_account_id:
            self.add_member(community_id, owner_account_id, "owner")
        return community

    def get_community(self, community_id):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM communities WHERE community_id=?",
                (community_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_communities(self, account_id=None, limit=50):
        with self.connect() as conn:
            if account_id:
                rows = conn.execute(
                    """
                    SELECT c.* FROM communities c
                    JOIN community_members m ON m.community_id = c.community_id
                    WHERE m.account_id=?
                    ORDER BY c.created_ms DESC LIMIT ?
                    """,
                    (account_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM communities ORDER BY created_ms DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def add_member(self, community_id, account_id, role="member"):
        with self.connect() as conn, conn:
            conn.execute(
                """
                INSERT INTO community_members(
                    community_id, account_id, role, joined_ms
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(community_id, account_id) DO UPDATE SET role=excluded.role
                """,
                (community_id, account_id, role, int(time.time() * 1000)),
            )

    def list_members(self, community_id):
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT m.role, m.joined_ms, a.*
                FROM community_members m
                JOIN accounts a ON a.account_id = m.account_id
                WHERE m.community_id=?
                ORDER BY m.joined_ms
                """,
                (community_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def count_members(self, community_id):
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM community_members WHERE community_id=?",
                (community_id,),
            ).fetchone()[0]

    def insert_channel(
        self,
        channel_id,
        community_id,
        name,
        description="",
        key_b64=None,
        created_ms=None,
    ):
        with self.connect() as conn, conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO channels(
                    channel_id, community_id, name, description,
                    key_b64, created_ms
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    channel_id,
                    community_id,
                    name,
                    description,
                    key_b64 or _b64e(os.urandom(16)),
                    int(created_ms or time.time() * 1000),
                ),
            )
        return self.get_channel(channel_id)

    def create_channel(self, community_id, name="geral", description=""):
        channel_id = f"{community_id}-{uuid.uuid4().hex[:10]}"
        return self.insert_channel(channel_id, community_id, name, description)

    def get_channel(self, channel_id):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM channels WHERE channel_id=?", (channel_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_channels(self, community_id=None, account_id=None):
        with self.connect() as conn:
            if community_id:
                rows = conn.execute(
                    "SELECT * FROM channels WHERE community_id=? ORDER BY created_ms",
                    (community_id,),
                ).fetchall()
            elif account_id:
                rows = conn.execute(
                    """
                    SELECT ch.* FROM channels ch
                    JOIN community_members m ON m.community_id = ch.community_id
                    WHERE m.account_id=?
                    ORDER BY ch.created_ms
                    """,
                    (account_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM channels ORDER BY created_ms"
                ).fetchall()
        return [dict(row) for row in rows]

    def add_message(
        self,
        channel_id,
        author_account_id,
        text,
        message_id=None,
        created_us=None,
        client_id=None,
    ):
        message_id = message_id or _b64e(os.urandom(32))
        with self.connect() as conn, conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO channel_messages(
                    message_id, channel_id, author_account_id, text,
                    created_us, client_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    channel_id,
                    author_account_id,
                    text,
                    int(created_us or time.time() * 1_000_000),
                    client_id,
                ),
            )
            row = conn.execute(
                "SELECT * FROM channel_messages WHERE message_id=?",
                (message_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_messages(self, channel_id, limit=100):
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT m.*, a.omlet_id AS author_omlet_id
                FROM channel_messages m
                JOIN accounts a ON a.account_id = m.author_account_id
                WHERE m.channel_id=?
                ORDER BY m.created_us
                LIMIT ?
                """,
                (channel_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def count_messages(self, channel_id):
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM channel_messages WHERE channel_id=?",
                (channel_id,),
            ).fetchone()[0]

    def migrate_json(
        self,
        accounts_path,
        state_path,
        default_post_id,
        default_community_id,
        default_channel_id,
        default_channel_key,
        seed_title,
        seed_description,
    ):
        state = {}
        if os.path.exists(state_path):
            try:
                with open(state_path, "r", encoding="utf-8") as fh:
                    state = json.load(fh)
            except Exception as exc:
                LOG.error("could not read state.json for migration: %r", exc)

        with self.connect() as conn:
            accounts_count = conn.execute(
                "SELECT COUNT(*) FROM accounts"
            ).fetchone()[0]
            posts_count = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            communities_count = conn.execute(
                "SELECT COUNT(*) FROM communities"
            ).fetchone()[0]
            channels_count = conn.execute(
                "SELECT COUNT(*) FROM channels"
            ).fetchone()[0]

        if accounts_count == 0 and os.path.exists(accounts_path):
            try:
                with open(accounts_path, "r", encoding="utf-8") as fh:
                    records = json.load(fh).get("records", [])
                for record in records:
                    if isinstance(record, dict) and record.get("account_id"):
                        record.setdefault("has_email", True)
                        record.setdefault("has_password", True)
                        self.upsert_account(record)
                LOG.info("migrated %d accounts from accounts.json", len(records))
            except Exception as exc:
                LOG.error("could not migrate accounts.json: %r", exc)

        accounts = self.all_accounts()
        owner = accounts[0] if accounts else None
        owner_id = owner["account_id"] if owner else None

        community_data = state.get("community") if isinstance(state, dict) else None
        if not isinstance(community_data, dict):
            community_data = {}

        if communities_count == 0:
            self.insert_community(
                default_community_id,
                community_data.get("name") or "Comunidade Local",
                community_data.get("description") or "Comunidade local de testes",
                community_data.get("icon") or self.default_icon,
                community_data.get("cover") or self.default_cover,
                owner_id,
            )
            if owner_id:
                self.add_member(default_community_id, owner_id, "owner")
            LOG.info("seeded default community %s", default_community_id)

        if channels_count == 0:
            self.insert_channel(
                default_channel_id,
                default_community_id,
                "geral",
                "Canal de texto da comunidade",
                default_channel_key,
            )
            LOG.info("seeded default channel %s", default_channel_id)

        if posts_count == 0 and isinstance(state, dict):
            posts = state.get("posts")
            if isinstance(posts, dict):
                for post_id, post_state in posts.items():
                    if not isinstance(post_state, dict):
                        continue
                    author_id = owner_id
                    if not author_id:
                        continue
                    liked = bool(post_state.get("liked", False))
                    legacy_count = max(
                        0, int(post_state.get("count", 0)) - (1 if liked else 0)
                    )
                    comments = post_state.get("comments")
                    comment_rows = []
                    if isinstance(comments, list):
                        for comment in comments:
                            if not isinstance(comment, dict):
                                continue
                            author = comment.get("u") or {}
                            comment_author_id = author.get("a") or owner_id
                            if not comment_author_id:
                                continue
                            self.ensure_account(
                                comment_author_id,
                                author.get("n") or "omletplayer",
                            )
                            comment_rows.append(
                                (
                                    comment.get("i")
                                    or _b64e(os.urandom(8)),
                                    comment_author_id,
                                    _decode_text(comment.get("b", "")),
                                    int(
                                        comment.get("t")
                                        or time.time() * 1000
                                    ),
                                    comment.get("i"),
                                )
                            )
                    with self.connect() as conn, conn:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO posts(
                                post_id, author_account_id, title, description,
                                created_ms, legacy_like_count
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                post_id,
                                author_id,
                                seed_title,
                                seed_description,
                                int(time.time() * 1000),
                                legacy_count,
                            ),
                        )
                        if liked:
                            conn.execute(
                                "INSERT OR IGNORE INTO post_likes("
                                "post_id, account_id, created_ms) VALUES (?, ?, ?)",
                                (post_id, author_id, int(time.time() * 1000)),
                            )
                        for (
                            comment_id,
                            comment_author_id,
                            text,
                            created_ms,
                            client_id,
                        ) in comment_rows:
                            conn.execute(
                                """
                                INSERT OR IGNORE INTO comments(
                                    comment_id, post_id, author_account_id,
                                    text, created_ms, client_id
                                ) VALUES (?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    comment_id,
                                    post_id,
                                    comment_author_id,
                                    text,
                                    created_ms,
                                    client_id,
                                ),
                            )
                LOG.info("migrated posts from state.json")

        posts_count = len(self.list_posts(limit=1000))
        if posts_count == 0 and owner_id:
            self.ensure_post(
                default_post_id,
                owner_id,
                seed_title,
                seed_description,
            )
            LOG.info("seeded default post %s", default_post_id)

        channels = state.get("channels") if isinstance(state, dict) else None
        if isinstance(channels, dict):
            for channel_id, channel_state in channels.items():
                if not isinstance(channel_state, dict):
                    continue
                if channel_id != default_channel_id:
                    self.insert_channel(
                        channel_id,
                        default_community_id,
                        "geral",
                        "Canal de texto da comunidade",
                    )
                messages = channel_state.get("messages")
                if not isinstance(messages, list):
                    continue
                for message in messages:
                    if not isinstance(message, dict):
                        continue
                    author = message.get("s") or owner_id
                    if not author:
                        continue
                    self.ensure_account(author)
                    msg_id = message.get("i") or {}
                    message_id = (
                        msg_id.get("i")
                        if isinstance(msg_id, dict)
                        else None
                    ) or _b64e(os.urandom(32))
                    self.add_message(
                        channel_id,
                        author,
                        _decode_text(message.get("b", "")),
                        message_id=message_id,
                        created_us=int(
                            message.get("t") or time.time() * 1_000_000
                        ),
                        client_id=message_id,
                    )
            LOG.info("migrated channel messages from state.json")
