"""SQLite database layer for the War Empire Telegram bot.

State is scoped PER GROUP (chat_id): a user has independent coins/team/projects
in every group where they /start the bot.
"""
import sqlite3
import time
from contextlib import contextmanager
from typing import Optional, Iterator

DB_PATH = "empire.db"

STARTING_COINS = 5000


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate_to_per_chat(conn: sqlite3.Connection) -> None:
    """If the legacy schema (no chat_id on users) is detected, drop and recreate
    user/team/project/join_requests tables. Existing in-game progress is wiped
    intentionally because the model changes from global to per-chat."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(users)")
    cols = [r[1] for r in cur.fetchall()]
    if cols and "chat_id" not in cols:
        cur.executescript(
            """
            DROP TABLE IF EXISTS join_requests;
            DROP TABLE IF EXISTS projects;
            DROP TABLE IF EXISTS teams;
            DROP TABLE IF EXISTS users;
            """
        )


def init_db() -> None:
    with get_conn() as conn:
        _migrate_to_per_chat(conn)
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                username TEXT,
                first_name TEXT,
                coins INTEGER NOT NULL DEFAULT 0,
                team_id INTEGER,
                joined_at INTEGER NOT NULL,
                PRIMARY KEY (user_id, chat_id)
            );

            CREATE TABLE IF NOT EXISTS teams (
                team_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                leader_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                join_locked INTEGER NOT NULL DEFAULT 0,
                attack_locked INTEGER NOT NULL DEFAULT 0,
                soldiers INTEGER NOT NULL DEFAULT 0,
                missiles INTEGER NOT NULL DEFAULT 0,
                antimissiles INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                UNIQUE(name, chat_id)
            );

            CREATE TABLE IF NOT EXISTS join_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                team_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL,
                UNIQUE(user_id, team_id)
            );

            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                ptype TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                last_payout_at INTEGER NOT NULL,
                damage INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                title TEXT,
                registered_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS auctions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER,
                item_key TEXT NOT NULL,
                item_name TEXT NOT NULL,
                current_bid INTEGER NOT NULL DEFAULT 0,
                current_bidder INTEGER,
                bidder_name TEXT,
                ends_at INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            );
            """
        )


# ---------- USERS (per-chat) ----------

def get_or_create_user(user_id: int, chat_id: int, username: Optional[str], first_name: Optional[str]) -> sqlite3.Row:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO users (user_id, chat_id, username, first_name, coins, joined_at) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, chat_id, username, first_name, STARTING_COINS, int(time.time())),
            )
            cur.execute("SELECT * FROM users WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
            row = cur.fetchone()
        else:
            if row["username"] != username or row["first_name"] != first_name:
                cur.execute(
                    "UPDATE users SET username = ?, first_name = ? WHERE user_id = ? AND chat_id = ?",
                    (username, first_name, user_id, chat_id),
                )
                cur.execute("SELECT * FROM users WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
                row = cur.fetchone()
        return row


def get_user(user_id: int, chat_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
        return cur.fetchone()


def add_coins(user_id: int, chat_id: int, amount: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET coins = coins + ? WHERE user_id = ? AND chat_id = ?",
            (amount, user_id, chat_id),
        )


def set_user_coins(user_id: int, chat_id: int, value: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET coins = ? WHERE user_id = ? AND chat_id = ?",
            (value, user_id, chat_id),
        )


def reset_all_coins_in_chat(chat_id: int) -> int:
    with get_conn() as conn:
        cur = conn.execute("UPDATE users SET coins = 0 WHERE chat_id = ?", (chat_id,))
        return cur.rowcount


def set_user_team(user_id: int, chat_id: int, team_id: Optional[int]) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET team_id = ? WHERE user_id = ? AND chat_id = ?",
            (team_id, user_id, chat_id),
        )


def list_users_in_chat(chat_id: int) -> list:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,))
        return cur.fetchall()


# ---------- TEAMS (scoped per chat_id) ----------

def create_team(name: str, leader_id: int, chat_id: int) -> Optional[int]:
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO teams (name, leader_id, chat_id, created_at) VALUES (?, ?, ?, ?)",
                (name, leader_id, chat_id, int(time.time())),
            )
            team_id = cur.lastrowid
            cur.execute(
                "UPDATE users SET team_id = ? WHERE user_id = ? AND chat_id = ?",
                (team_id, leader_id, chat_id),
            )
            return team_id
    except sqlite3.IntegrityError:
        return None


def get_team(team_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM teams WHERE team_id = ?", (team_id,))
        return cur.fetchone()


def list_open_teams(chat_id: int, limit: int = 20) -> list:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM teams WHERE chat_id = ? AND join_locked = 0 ORDER BY created_at DESC LIMIT ?",
            (chat_id, limit),
        )
        return cur.fetchall()


def list_all_teams_in_chat(chat_id: int) -> list:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM teams WHERE chat_id = ? ORDER BY created_at DESC", (chat_id,))
        return cur.fetchall()


def get_team_members(team_id: int) -> list:
    """Members of a team (team is already chat-scoped)."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT u.* FROM users u
               JOIN teams t ON t.team_id = ? AND u.chat_id = t.chat_id
               WHERE u.team_id = ?
               ORDER BY u.user_id""",
            (team_id, team_id),
        )
        return cur.fetchall()


def toggle_team_flag(team_id: int, flag: str) -> int:
    assert flag in ("join_locked", "attack_locked")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT {flag} FROM teams WHERE team_id = ?", (team_id,))
        row = cur.fetchone()
        new_val = 0 if row[0] else 1
        cur.execute(f"UPDATE teams SET {flag} = ? WHERE team_id = ?", (new_val, team_id))
        return new_val


def add_to_vault(team_id: int, kind: str, qty: int) -> None:
    assert kind in ("soldiers", "missiles", "antimissiles")
    with get_conn() as conn:
        conn.execute(f"UPDATE teams SET {kind} = {kind} + ? WHERE team_id = ?", (qty, team_id))


def consume_attack_units(team_id: int, soldiers: int, missiles: int) -> bool:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT soldiers, missiles FROM teams WHERE team_id = ?", (team_id,))
        row = cur.fetchone()
        if not row or row["soldiers"] < soldiers or row["missiles"] < missiles:
            return False
        cur.execute(
            "UPDATE teams SET soldiers = soldiers - ?, missiles = missiles - ? WHERE team_id = ?",
            (soldiers, missiles, team_id),
        )
        return True


def consume_defense(team_id: int, defense_used: int) -> None:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT antimissiles FROM teams WHERE team_id = ?", (team_id,))
        row = cur.fetchone()
        if row:
            new_val = max(0, row["antimissiles"] - defense_used)
            cur.execute("UPDATE teams SET antimissiles = ? WHERE team_id = ?", (new_val, team_id))


def reset_user_soldiers(user_id: int, chat_id: int) -> bool:
    """Set team's soldiers to 0 for the user's team in this chat."""
    u = get_user(user_id, chat_id)
    if not u or not u["team_id"]:
        return False
    with get_conn() as conn:
        conn.execute("UPDATE teams SET soldiers = 0 WHERE team_id = ?", (u["team_id"],))
    return True


def reset_all_soldiers_in_chat(chat_id: int) -> int:
    with get_conn() as conn:
        cur = conn.execute("UPDATE teams SET soldiers = 0 WHERE chat_id = ?", (chat_id,))
        return cur.rowcount


# ---------- JOIN REQUESTS ----------

def create_join_request(user_id: int, team_id: int, chat_id: int) -> Optional[int]:
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO join_requests (user_id, team_id, chat_id, created_at) VALUES (?, ?, ?, ?)",
                (user_id, team_id, chat_id, int(time.time())),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def get_join_request(req_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM join_requests WHERE id = ?", (req_id,))
        return cur.fetchone()


def update_join_request(req_id: int, status: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE join_requests SET status = ? WHERE id = ?", (status, req_id))


def list_pending_requests_for_team(team_id: int) -> list:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM join_requests WHERE team_id = ? AND status = 'pending'",
            (team_id,),
        )
        return cur.fetchall()


# ---------- PROJECTS (per-chat via chat_id column) ----------

def add_projects_bulk(owner_id: int, chat_id: int, ptype: str, count: int) -> list:
    ids = []
    now = int(time.time())
    with get_conn() as conn:
        cur = conn.cursor()
        for _ in range(count):
            cur.execute(
                "INSERT INTO projects (owner_id, chat_id, ptype, created_at, last_payout_at, damage, level) VALUES (?, ?, ?, ?, ?, 0, 0)",
                (owner_id, chat_id, ptype, now, now),
            )
            ids.append(cur.lastrowid)
    return ids


def get_user_projects(owner_id: int, chat_id: int) -> list:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM projects WHERE owner_id = ? AND chat_id = ? ORDER BY id",
            (owner_id, chat_id),
        )
        return cur.fetchall()


def delete_user_projects(owner_id: int, chat_id: int) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM projects WHERE owner_id = ? AND chat_id = ?",
            (owner_id, chat_id),
        )
        return cur.rowcount


def delete_all_projects_in_chat(chat_id: int) -> int:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM projects WHERE chat_id = ?", (chat_id,))
        return cur.rowcount


def get_all_projects() -> list:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM projects")
        return cur.fetchall()


def update_project_payout(project_id: int, ts: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE projects SET last_payout_at = ? WHERE id = ?", (ts, project_id))


def upgrade_projects(project_ids: list) -> None:
    if not project_ids:
        return
    with get_conn() as conn:
        cur = conn.cursor()
        for pid in project_ids:
            cur.execute("UPDATE projects SET level = level + 1 WHERE id = ?", (pid,))


def apply_project_damage(project_id: int, additional_pct: int) -> tuple:
    """Add damage to a project. If total damage >= 100, deletes the project.
    Returns (new_damage, destroyed: bool)."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT damage FROM projects WHERE id = ?", (project_id,))
        row = cur.fetchone()
        if not row:
            return (0, False)
        new_dmg = row["damage"] + additional_pct
        if new_dmg >= 100:
            cur.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            return (100, True)
        cur.execute("UPDATE projects SET damage = ? WHERE id = ?", (new_dmg, project_id))
        return (new_dmg, False)


def random_projects_for_team(team_id: int, n: int) -> list:
    """Random projects owned by members of the team (members are chat-scoped via team)."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT p.* FROM projects p
               JOIN teams t ON t.team_id = ?
               WHERE p.chat_id = t.chat_id
                 AND p.owner_id IN (SELECT user_id FROM users WHERE team_id = ? AND chat_id = t.chat_id)
               ORDER BY RANDOM() LIMIT ?""",
            (team_id, team_id, n),
        )
        return cur.fetchall()


# ---------- TEAM ADMIN HELPERS ----------

def delete_team(team_id: int) -> None:
    """Disband: clear users.team_id where they belong, drop join requests, remove team."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET team_id = NULL WHERE team_id = ?", (team_id,))
        cur.execute("DELETE FROM join_requests WHERE team_id = ?", (team_id,))
        cur.execute("DELETE FROM teams WHERE team_id = ?", (team_id,))


def add_to_user_team_vault(user_id: int, chat_id: int, field: str, qty: int) -> bool:
    u = get_user(user_id, chat_id)
    if not u or not u["team_id"]:
        return False
    add_to_vault(u["team_id"], field, qty)
    return True


# ---------- AUCTION CLEANUP & STATS ----------

def cleanup_stale_auctions() -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE auctions SET status = 'expired' WHERE status = 'active'"
        )
        return cur.rowcount


def admin_global_stats() -> dict:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c, COALESCE(SUM(coins),0) AS s FROM users")
        u_row = cur.fetchone()
        cur.execute("SELECT COUNT(DISTINCT user_id) AS c FROM users")
        uniq_row = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS c FROM teams")
        t_row = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS c FROM projects")
        p_row = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS c FROM chats")
        c_row = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS c FROM auctions WHERE status = 'active'")
        a_row = cur.fetchone()
        return {
            "users": u_row["c"],
            "unique_users": uniq_row["c"],
            "total_coins": u_row["s"],
            "teams": t_row["c"],
            "projects": p_row["c"],
            "chats": c_row["c"],
            "active_auctions": a_row["c"],
        }


def admin_chat_stats(chat_id: int) -> dict:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS c, COALESCE(SUM(coins),0) AS s FROM users WHERE chat_id = ?",
            (chat_id,),
        )
        u_row = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS c FROM teams WHERE chat_id = ?", (chat_id,))
        t_row = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS c FROM projects WHERE chat_id = ?", (chat_id,))
        p_row = cur.fetchone()
        return {
            "users": u_row["c"],
            "total_coins": u_row["s"],
            "teams": t_row["c"],
            "projects": p_row["c"],
        }


# ---------- LEADERBOARD (per-chat) ----------

def top_players_by_coins(chat_id: int, limit: int = 10) -> list:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM users WHERE chat_id = ? ORDER BY coins DESC LIMIT ?",
            (chat_id, limit),
        )
        return cur.fetchall()


def top_teams_by_power(chat_id: int, limit: int = 10) -> list:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT *, (soldiers*10 + missiles*50 + antimissiles*40) AS power
               FROM teams WHERE chat_id = ?
               ORDER BY power DESC, name ASC LIMIT ?""",
            (chat_id, limit),
        )
        return cur.fetchall()


def top_teams_by_wealth(chat_id: int, limit: int = 10) -> list:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT t.*, COALESCE(SUM(u.coins), 0) AS total_wealth,
                      COUNT(u.user_id) AS member_count
               FROM teams t
               LEFT JOIN users u ON u.team_id = t.team_id AND u.chat_id = t.chat_id
               WHERE t.chat_id = ?
               GROUP BY t.team_id
               ORDER BY total_wealth DESC LIMIT ?""",
            (chat_id, limit),
        )
        return cur.fetchall()


# ---------- CHATS ----------

def register_chat(chat_id: int, title: Optional[str]) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO chats (chat_id, title, registered_at) VALUES (?, ?, COALESCE((SELECT registered_at FROM chats WHERE chat_id = ?), ?))",
            (chat_id, title, chat_id, int(time.time())),
        )


def list_chats() -> list:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM chats")
        return cur.fetchall()


# ---------- AUCTIONS ----------

def create_auction(chat_id: int, item_key: str, item_name: str, ends_at: int) -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO auctions (chat_id, item_key, item_name, ends_at) VALUES (?, ?, ?, ?)",
            (chat_id, item_key, item_name, ends_at),
        )
        return cur.lastrowid


def set_auction_message(auction_id: int, message_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE auctions SET message_id = ? WHERE id = ?", (message_id, auction_id))


def get_auction(auction_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM auctions WHERE id = ?", (auction_id,))
        return cur.fetchone()


def place_bid(auction_id: int, user_id: int, chat_id: int, name: str, increment: int) -> Optional[sqlite3.Row]:
    """Atomically try to place a bid using user's per-chat balance."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM auctions WHERE id = ?", (auction_id,))
        auc = cur.fetchone()
        if not auc or auc["status"] != "active":
            return None
        if int(time.time()) > auc["ends_at"]:
            return None
        if auc["chat_id"] != chat_id:
            return None
        new_bid = auc["current_bid"] + increment
        cur.execute(
            "SELECT coins FROM users WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        )
        u = cur.fetchone()
        if not u or u["coins"] < new_bid:
            return None
        if auc["current_bidder"]:
            cur.execute(
                "UPDATE users SET coins = coins + ? WHERE user_id = ? AND chat_id = ?",
                (auc["current_bid"], auc["current_bidder"], chat_id),
            )
        cur.execute(
            "UPDATE users SET coins = coins - ? WHERE user_id = ? AND chat_id = ?",
            (new_bid, user_id, chat_id),
        )
        cur.execute(
            "UPDATE auctions SET current_bid = ?, current_bidder = ?, bidder_name = ? WHERE id = ?",
            (new_bid, user_id, name, auction_id),
        )
        cur.execute("SELECT * FROM auctions WHERE id = ?", (auction_id,))
        return cur.fetchone()


def close_auction(auction_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM auctions WHERE id = ?", (auction_id,))
        auc = cur.fetchone()
        if not auc or auc["status"] != "active":
            return None
        cur.execute("UPDATE auctions SET status = 'ended' WHERE id = ?", (auction_id,))
        cur.execute("SELECT * FROM auctions WHERE id = ?", (auction_id,))
        return cur.fetchone()


def get_active_auction_in_chat(chat_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM auctions WHERE chat_id = ? AND status = 'active'",
            (chat_id,),
        )
        return cur.fetchone()
