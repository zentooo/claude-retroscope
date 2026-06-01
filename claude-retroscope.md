# Claude Retroscope — 実装方針

Claude Code のセッション履歴を分析し、作業レポート・改善提案・インストラクション更新案を生成する CLI ツール。
GitHub Copilot CLI の `/chronicle` を参考にするが、**cman のコード・データ構造は流用しない**。
データ取得元（`~/.claude/` 配下）と JSONL のパース方針だけを参考に、独立したプロジェクトとして設計する。

---

## 背景と目的

| 項目 | 内容 |
|------|------|
| 参考 | [GitHub Copilot CLI の `/chronicle`](https://zenn.dev/aeonpeople/articles/morihaya-20260527-copilot-cli-chronicle) |
| 対象 | Claude Code CLI + Claude Desktop **Code タブ**（Cowork / Chat は Phase 4+） |
| cman との関係 | 競合・置き換えではなく、**分析特化の別ツール**。cman は検索・記憶のエージェント補助、Retroscope は構造化分析とレポート生成 |

Copilot `/chronicle` が `session-store.db`（SQLite）を前提とするのに対し、Retroscope は Claude Code が既に書き込んでいる JSONL を一次ソースとし、**ローカルインデックス DB を自前で持つ**設計とする。

---

## 設計原則

1. **ソース・オブ・トゥルースは Claude Code の生ログ** — 追加の計測基盤をユーザーに要求しない
2. **構造化レイヤーを自前で持つ** — 毎回全 JSONL を LLM に丸投げしない（Copilot の session-store 相当）
3. **決定的パース + 非決定的要約を分離** — メトリクス集計はコード、自然言語レポートは LLM
4. **プライバシー明示** — 分析コマンド実行時も LLM API にセッション断片が送られる点をドキュメント化
5. **cman 非依存** — コード・データ構造は共有しないが、**ランタイム構成（Python + uv + stdlib sqlite3）は cman と同型**（下記）

---

## ランタイム・スタック（cman 同型）

Claude Code 本体は Bun 製だが、**同梱 Bun をプラグインから使う手段は現行 native binary では使えない**（`BUN_BE_BUN=1` は 2.1.35 以降非対応、[GitHub #24575](https://github.com/anthropics/claude-code/issues/24575)）。claude-mem 型（別途 Bun + `bun:sqlite`）は環境依存が増えるため採用しない。

| 項目 | 選定 |
|------|------|
| 言語 | **Python 3.12+** |
| ランナー | **[uv](https://docs.astral.sh/uv/)** `uv run --script`（cman と同じ） |
| DB | **stdlib `sqlite3`**（追加ネイティブ依存なし） |
| MCP（将来） | FastMCP + stdio（cman の `server.py` パターン） |
| データ dir | `~/.retroscope/`（上書き: `RETROSCOPE_DATA_DIR`） |

### なぜ cman と同じか

- cman 利用者は **uv を既に入れている**可能性が高い
- Python `sqlite3` は OS 付属で **ビルド地獄がない**（`better-sqlite3` / `bun:sqlite` より予測可能）
- ingest・集計・SQL クエリ向き
- プラグイン化時も `.mcp.json` が cman と同一形:

```json
{
  "retroscope": {
    "command": "uv",
    "args": ["run", "--script", "${CLAUDE_PLUGIN_ROOT}/server.py"]
  }
}
```

### エントリポイント（PEP 723 inline script）

cman の `server.py` と同様、ファイル先頭で依存を宣言:

```python
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
```

CLI 本体は `retroscope.py`（または `scripts/` 配下を import する thin wrapper）。Phase 1 は MCP なしの **スタンドアロン CLI のみ**。Phase 4 で `server.py` + スキルを足す。

### 実行例

```bash
# スタンドアロン
uv run --script retroscope.py standup
uv run --script retroscope.py search "auth"

# 開発
uv run --script retroscope.py status
```

### DB の位置づけ（再確認）

- **SoT**: `~/.claude/projects/**/*.jsonl`（変更なし）
- **派生キャッシュ**: `~/.retroscope/store.db` — `retroscope reindex` で再構築可能
- cman は DB を持たないが、Retroscope は chronicle 系の集計のため SQLite を追加する点だけが異なる


## データソース（参考: cman 調査結果）

cman が読んでいるパスを起点に、Retroscope が利用するソースを整理する。

### 一次ソース: セッションログ

```
~/.claude/projects/<encoded-project-path>/
  ├── <session-id>.jsonl          # メインセッション
  └── <session-id>/
      └── subagents/
          └── agent-<id>.jsonl    # サブエージェント（デフォルト除外）
```

- 形式: JSONL（1 行 1 JSON オブジェクト）
- ファイル stem = `session_id`
- プロジェクトディレクトリ名は cwd のエンコード（例: `-Users-naosuke-repos-cman`）

**cman との違い:** cman はファイル `mtime` で時系列を近似していた。Retroscope は行レベルの `timestamp` を正とする。

### 二次ソース

| パス | 用途 |
|------|------|
| `~/.claude/plans/<slug>.md` | プランタイトル・進行中タスクの文脈 |
| `~/.claude/history.jsonl` | 全プロジェクト横断の入力履歴（search 用、resume 不可） |
| `CLAUDE.md` / `~/.claude/CLAUDE.md` / `~/.claude/rules/**/*.md` | improve コマンドの更新対象 |
| `{project}/.claude/projects/*/memory/*.md` | auto-memory（improve の参照コンテキスト） |

### JSONL レコード種別（観測済み）

パーサは `type` フィールドで分岐する。未知の type は警告ログを残してスキップ（前方互換）。

| type | 主なフィールド | Retroscope での扱い |
|------|---------------|-------------------|
| `user` | `message`, `timestamp`, `cwd`, `gitBranch`, `slug`, `toolUseResult` | イベント・メトリクス・検索インデックス |
| `assistant` | `message`（text / tool_use / thinking）, `message.usage` | トークン集計・ツール呼び出し分析 |
| `summary` | `summary` | セッションタイトル候補 |
| `system` | `content` | 検索インデックス |
| `attachment` | `attachment.type`（plan_mode, skill_listing 等） | コンテキストメタデータ |
| `ai-title` | `aiTitle` | セッションタイトル（summary より優先） |
| `file-history-snapshot` | `snapshot.trackedFileBackups` | 編集ファイル追跡 |
| `mode`, `permission-mode` | `mode`, `permissionMode` | セッション状態 |
| その他 | — | 無視（ログのみ） |

### cman が使っていなかったが Retroscope が使うフィールド

```json
{
  "timestamp": "2026-06-01T07:18:28.627Z",
  "gitBranch": "main",
  "cwd": "/Users/naosuke/repos/cman",
  "slug": "https-zenn-dev-aeonpeople-articles-morih-purring-scone",
  "message": {
    "usage": {
      "input_tokens": 3,
      "output_tokens": 541,
      "cache_read_input_tokens": 12326,
      "cache_creation_input_tokens": 7934
    }
  }
}
```

---

## Claude Desktop 対応方針

Desktop 対応の難易度は **OS パス調査より、保存形式の多様性と Anthropic 側の変更頻度** に左右される。パス自体はテーブル駆動で足せるが、ストレージレイヤの churn が長期メンテコストの主因になる。

### 難易度サマリ

| スコープ | Phase | 難易度 | 目安 |
|---------|-------|--------|------|
| CLI + Desktop Code タブ（会話本文あり） | 1 | ★★☆ | Phase 1 に含む（追加実装ほぼ不要） |
| Desktop 索引（`local_*.json`）の join | 1.5 | ★★☆ | 数日〜1 週間 |
| Cowork / Chat（`audit.jsonl`） | 4+ | ★★★★ | 別 Adapter 級（2 週間以上） |
| VM bundle（`sessiondata.img`） | — | ★★★★★ | **非スコープ**（暗号化、非公開） |

### 重要: 会話本文は Desktop 専用フォーマットではない

Desktop **Code タブ** のセッションは、CLI と同様 **`~/.claude/projects/**/*.jsonl` に会話本文が書かれる** ケースが主流（[GitHub #29373](https://github.com/anthropics/claude-code/issues/29373)、[#58670](https://github.com/anthropics/claude-code/issues/58670) 等でコミュニティ確認済み）。

Desktop 側が追加で持つのは **サイドバー用の索引ファイル** `local_*.json` のみ。本文パーサを Desktop 用に別途書く必要は基本的にない。

```
Desktop UI (sidebar)
    │
    ▼
local_*.json  ──cliSessionId──▶  ~/.claude/projects/.../<session-id>.jsonl
   (メタデータ)                        (会話本文 = Retroscope の一次ソース)
```

Phase 1 で JSONL ingest を実装すれば、**Desktop Code タブ由来セッションの大半は自動的にカバー** される。Phase 1.5 では索引との join と欠損検出を足す。

### OS 別パス（PathResolver）

公式ドキュメントは CLI の `~/.claude/` のみ。Desktop パスはコミュニティ逆引き + issue 追跡が前提。

| 用途 | macOS | Windows | Linux |
|------|-------|---------|-------|
| 会話 JSONL（CLI / Desktop Code 共通） | `~/.claude/projects/` | `%USERPROFILE%\.claude\projects\` | `~/.claude/projects/` |
| Desktop 索引（現行） | `~/Library/Application Support/Claude/claude-code-sessions/` | `%APPDATA%\Claude\claude-code-sessions\` | Desktop 本体未サポート（CLI のみ） |
| Desktop 索引（旧名） | `.../Claude/local-agent-mode-sessions/` | 同上 | — |
| Cowork (3P) | `~/Library/Application Support/Claude-3p/` | `%LOCALAPPDATA%\Claude-3p\` | — |
| VM bundle（読取不可） | `.../Claude/vm_bundles/claudevm.bundle/` | 同上 | — |

索引の実パス構造:

```
<desktop-root>/claude-code-sessions/<accountId>/<orgId>/local_<uuid>.json
```

- **複数アカウント**: `accountId` ディレクトリごとにセッションが分離される。Desktop UI は**ログイン中アカウント分のみ**表示するが、ディスク上には旧アカウント分も残る（[DEV 記事](https://dev.to/arthurpro/45-mb-of-claude-code-sessions-you-dont-see-clj): 715 件 on disk vs 69 件 in UI の例）。Retroscope は **全 `accountId/orgId` をスキャン** する。
- **レガシー fallback**: `local-agent-mode-sessions/` も glob 対象に含める（2026 年初頭のリネーム、[#29373](https://github.com/anthropics/claude-code/issues/29373)）。

### `local_*.json` スキーマ（コミュニティ逆引き）

Anthropic 非公式。フィールドは増減しうる。

```json
{
  "sessionId": "local_<desktop-uuid>",
  "cliSessionId": "<jsonl-file-stem>",
  "cwd": "/absolute/path",
  "originCwd": "/absolute/path",
  "createdAt": 1717000000000,
  "lastActivityAt": 1717000000000,
  "model": "claude-opus-4-6",
  "title": "sidebar label",
  "permissionMode": "default",
  "completedTurns": 15,
  "isArchived": false
}
```

| フィールド | 用途 |
|-----------|------|
| `cliSessionId` | JSONL との join キー。**欠落時は本文リンク不可** |
| `createdAt` / `lastActivityAt` | standup 期間フィルタ（epoch ms） |
| `title` | 索引タイトル（JSONL の `ai-title` と突合可能） |
| `cwd` | プロジェクトグルーピング |

VM/Cowork 由来のエントリは `vmProcessName` や `cwd` が `/sessions/` 始まり等 — **JSONL join 対象外** として除外する（[#29373](https://github.com/anthropics/claude-code/issues/29373)）。

### 索引と JSONL の整合性（3 パターン）

[#55418](https://github.com/anthropics/claude-code/issues/55418)、[#53717](https://github.com/anthropics/claude-code/issues/53717) より:

| 状態 | 意味 | Retroscope の扱い |
|------|------|------------------|
| `local_*.json` あり + `cliSessionId` あり + JSONL あり | 正常 | `source=desktop`, 全文分析可能 |
| `local_*.json` あり + `cliSessionId` **欠落** | メタデータのみ | `link_status=metadata_only`。`createdAt` ±30s で JSONL 候補を提示（best-effort） |
| `cliSessionId` あり + JSONL **欠落/スタブ** | 本文ロスト | `link_status=transcript_missing`。standup に「本文なし」と表示 |
| JSONL のみ（索引なし） | CLI 由来 or Desktop 未索引 | `source=cli`。Phase 1 からカバー |

### Phase 1.5: Desktop 索引 ingest

```
retroscope ingest [--sources cli,desktop]
```

1. `PathResolver` で OS 別 Desktop root を解決
2. `**/local_*.json` を glob（全 accountId/orgId）
3. `desktop_sessions` テーブルに upsert
4. `cliSessionId` で `sessions` と join
5. join 失敗時はタイムスタンプマッチを試行（±30s、同一 cwd 優先）

**完了基準:** Desktop 専用セッション（索引のみ）を standup に表示でき、CLI セッションと重複なく統合される。

### Phase 4+: Cowork / Chat（別 Adapter）

Cowork は Claude Desktop 3P モード向けに **別ディレクトリ・別フォーマット** を使う（[公式: User identity and local data](https://claude.com/docs/cowork/3p/data-storage)）。

| パス | 内容 |
|------|------|
| `Claude-3p/local-agent-mode-sessions/<accountId>/<orgId>/local_*.json` | セッションメタデータ |
| 同ディレクトリ配下の `audit.jsonl` | ツール呼び出し等の append-only ログ（HMAC チェーン、`.audit-key` は OS keychain） |

- JSONL とは **別スキーマ**。公式仕様なし。
- chronicle 相当を Cowork まで広げるなら `CoworkAdapter` + `audit.jsonl` パーサが必要。
- 需要とスキーマ安定性を見て Phase 4 以降で検討。

### 非対応: VM bundle

Claude Desktop 1.47xx 以降、一部ユーザーで `vm_bundles/claudevm.bundle/sessiondata.img`（magic `shdw`、暗号化コンテナ）への移行が報告されている（[#54428](https://github.com/anthropics/claude-code/issues/54428)）。

- 外部ツールからの読取は現時点で不可能。
- **Retroscope は非対応と明記** し、`local_*.json` / JSONL が存在する限り従来経路で ingest する。
- VM 移行完了後は Desktop 索引 ingest 自体が機能しなくなるリスクあり → README に churn 警告を記載。

### Desktop 対応のリスク（追加分）

| リスク | 対策 |
|--------|------|
| ストレージ形式の churn（年に数回） | Adapter パターン、`PathResolver` に fallback チェーン、パーサバージョン記録 |
| 複数アカウントで UI に見えないセッション | 全 accountId スキャン（Retroscope の差別化ポイント） |
| 索引と JSONL の不整合 | `link_status` 列 + standup で明示 |
| Desktop 実行中の索引上書き | ingest 前にファイルロック検出 or 警告（Desktop 終了推奨をヘルプに記載） |
| VM bundle 移行 | 非対応宣言、JSONL 経路が残る限り継続 ingest |

---

## アーキテクチャ

```
~/.claude/projects/**/*.jsonl          Claude Desktop: claude-code-sessions/**/local_*.json
        │                                              │
        └──────────────────┬───────────────────────────┘
                           ▼
  ┌─────────────┐
  │   Ingest    │  JSONL パース + Desktop 索引 join（Phase 1.5）
  └──────┬──────┘
         ▼
  ┌─────────────┐
  │  Index DB   │  ~/.retroscope/store.db (SQLite)
  └──────┬──────┘
         │
    ┌────┴────┬──────────┬──────────┐
    ▼         ▼          ▼          ▼
 standup   search     tips      improve
    │         │          │          │
    └────┬────┴────┬─────┴──────────┘
         ▼         ▼
   構造化クエリ   LLM 要約（オプション）
         │
         ▼
      ターミナル出力 / Markdown レポート
```

### cman との対比

| | cman | Retroscope |
|---|------|------------|
| ランタイム | Python + uv | **同左** |
| 永続化 | なし（JSONL 直読み） | SQLite インデックス（`~/.retroscope/store.db`） |
| 分析 | スキル指示 + Claude 解釈 | CLI が決定的集計 + LLM はレポート生成のみ（`--llm`） |
| 配布形態 | Claude Code プラグイン (MCP) | Phase 1: スタンドアロン CLI → Phase 4: プラグイン optional |
| 期間フィルタ | ファイル mtime | メッセージ timestamp |
| トークン分析 | 未対応 | usage フィールド集計 |

---

## インデックス DB スキーマ（案）

```sql
-- 取り込み管理
CREATE TABLE ingest_state (
  file_path     TEXT PRIMARY KEY,
  file_mtime    REAL NOT NULL,
  byte_offset   INTEGER NOT NULL DEFAULT 0,
  line_count    INTEGER NOT NULL DEFAULT 0,
  updated_at    TEXT NOT NULL
);

-- セッション（メインのみ。subagent は別テーブル or is_subagent フラグ）
CREATE TABLE sessions (
  session_id    TEXT PRIMARY KEY,
  project_key   TEXT NOT NULL,       -- encoded project dir name
  cwd           TEXT,
  slug          TEXT,
  title         TEXT,                -- ai-title > summary > 先頭 user prompt > desktop index
  git_branch    TEXT,
  started_at    TEXT,                -- 最初の timestamp
  ended_at      TEXT,                -- 最後の timestamp
  message_count INTEGER DEFAULT 0,
  is_subagent   INTEGER DEFAULT 0,
  source        TEXT DEFAULT 'cli',  -- cli | desktop
  link_status   TEXT DEFAULT 'linked' -- linked | metadata_only | transcript_missing
);

-- Desktop 索引（Phase 1.5）
CREATE TABLE desktop_sessions (
  desktop_session_id  TEXT PRIMARY KEY,  -- local_*.json の sessionId
  cli_session_id      TEXT,                -- cliSessionId → sessions.session_id
  account_id          TEXT NOT NULL,
  org_id              TEXT NOT NULL,
  index_path          TEXT NOT NULL,
  cwd                 TEXT,
  title               TEXT,
  model               TEXT,
  created_at_ms       INTEGER,
  last_activity_ms    INTEGER,
  completed_turns     INTEGER,
  FOREIGN KEY (cli_session_id) REFERENCES sessions(session_id)
);

-- メッセージイベント（検索・分析用）
CREATE TABLE events (
  id            INTEGER PRIMARY KEY,
  session_id    TEXT NOT NULL,
  event_type    TEXT NOT NULL,       -- user | assistant | tool_result | ...
  timestamp     TEXT,
  role          TEXT,
  git_branch    TEXT,
  cwd           TEXT,
  text          TEXT,                -- 検索用プレーンテキスト（正規化済み）
  tool_name     TEXT,
  tool_input    TEXT,                -- JSON
  stderr        TEXT,
  is_error      INTEGER DEFAULT 0,
  FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE INDEX idx_events_session ON events(session_id);
CREATE INDEX idx_events_timestamp ON events(timestamp);
CREATE INDEX idx_events_fts ON events(text);  -- FTS5 検討

-- トークン使用量（assistant 行から抽出）
CREATE TABLE token_usage (
  id                  INTEGER PRIMARY KEY,
  session_id          TEXT NOT NULL,
  timestamp           TEXT,
  model               TEXT,
  input_tokens        INTEGER,
  output_tokens       INTEGER,
  cache_read_tokens   INTEGER,
  cache_create_tokens INTEGER,
  FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

-- 集計済みメトリクス（tips / cost-tips 用、日次 or セッション単位）
CREATE TABLE session_metrics (
  session_id              TEXT PRIMARY KEY,
  user_turns              INTEGER,
  tool_calls              INTEGER,
  skill_reads             INTEGER,   -- Read で SKILL.md を読んだ回数
  repeated_skill_reads    INTEGER,
  pasted_chars            INTEGER,   -- 長文ペースト推定
  correction_signals      INTEGER,   -- ユーザー訂正パターン
  FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

-- プラン紐付け
CREATE TABLE plans (
  slug          TEXT PRIMARY KEY,
  title         TEXT,
  plan_path     TEXT,
  updated_at    TEXT
);

CREATE TABLE plan_sessions (
  slug          TEXT,
  session_id    TEXT,
  PRIMARY KEY (slug, session_id)
);
```

FTS5 は Phase 2 以降。Phase 1 は LIKE + トークン分割でも可。

---

## パイプライン: Ingest

### 増分取り込み

1. `~/.claude/projects/**/*.jsonl` を glob（`subagents/` 配下は `--include-subagents` 時のみ）
2. `ingest_state` とファイル `st_mtime` を比較
3. 変更あり → `byte_offset` 以降のみ追読（新規ファイルは先頭から）
4. 1 行ずつ JSON パース → 正規化イベントに変換 → DB upsert
5. セッション集約フィールド（`started_at`, `ended_at`, `title`）を更新

### パース方針（cman の grep.py を参考にしつつ再設計）

**参考にする点（cman）:**
- `type` による分岐
- user/assistant の `message.content` が string | array 両対応
- tool_use の `name` + `input` 抽出
- user 行の `toolUseResult.stdout` / `stderr`

**Retroscope 独自:**
- 各行の `timestamp`, `gitBranch`, `cwd` をイベントに付与（行内優先、セッション fallback）
- `assistant` 行の `message.usage` を `token_usage` に分解
- `attachment.type == "plan_mode"` から plan パスを抽出
- `type == "ai-title"` で title 更新
- subagent 判定: パスに `subagents/` を含む、または `isSidechain == true`

### reindex

```
retroscope reindex [--force]
```

- `ingest_state` をクリアし全 JSONL を再パース
- セッションファイル手動削除後、別マシンからの移行、DB 破損時に使用
- Copilot `/chronicle reindex` と同位置づけ

---

## コマンド設計

CLI 名: `retroscope`（エイリアス `rs` は任意）

### `retroscope standup [period]`

**相当:** `/chronicle standup`

```
retroscope standup                  # デフォルト: 過去 24 時間
retroscope standup --since 3d
retroscope standup --since 2026-05-28
```

**出力内容:**
- 期間内のセッションをプロジェクト（cwd）× gitBranch でグルーピング
- 完了 / 進行中の分類（直近 N 時間以内に activity あり → 進行中）
- 関連プラン（slug 経由）
- resume コマンド: `cd <cwd> && claude --resume <session_id>`
- PR 言及があれば events テキストから抽出（best-effort、gh 連携は Phase 3+）

**実装:** DB クエリで構造化 → LLM 要約は `--llm` フラグ時のみ（デフォルトはテンプレートベース）

### `retroscope search <query>`

**相当:** `/chronicle search`

```
retroscope search "DynamoDB billing"
retroscope search auth --limit 20 --project cman
```

**実装:** `events.text` 全文検索 + スコアリング（user/summary 重み付けは cman 参考: user=3, summary=3, assistant=1）

### `retroscope tips [focus]`

**相当:** `/chronicle tips`

```
retroscope tips
retroscope tips --focus prompting
retroscope tips --since 7d
```

**分析項目（決定的集計）:**
- スキル指定なしで同種作業を繰り返している
- 同一 SKILL.md の Read がセッション内で N 回以上
- 短いセッションの乱立（30 分未満で終了 × 同一 cwd）
- plan mode 未使用の複数ステップタスク
- `@` / Read ツール比率（ファイル参照 vs ペースト推定）

**出力:** 集計結果 + LLM による 3〜5 件の actionable tips（`--no-llm` で集計のみ）

### `retroscope cost-tips [focus]`

**相当:** `/chronicle cost-tips`

```
retroscope cost-tips
retroscope cost-tips --since 7d
```

**分析項目:**
- セッション別・日別トークン合計（input / output / cache_read / cache_create）
- cache_create 比率が高いセッション（大コンテキスト再投入）
- 長セッション（turn 数 × トークン累積）
- 同一スキル反復 Read による cache_create 増
- subagent 起動コスト

**出力:** コスト削減の具体的 tips（Claude Code 固有: `/compact`, `/clear`, スキル事前指定, セッション分割）

### `retroscope improve [--apply]`

**相当:** `/chronicle improve`

```
retroscope improve
retroscope improve --project /path/to/repo
retroscope improve --apply   # CLAUDE.md / rules への diff 適用（要確認プロンプト）
```

**摩擦シグナル検出:**
- `toolUseResult.is_error == true` または stderr に build/test failure パターン
- 同一セッション内で同種エラーが 2 回以上
- ユーザー prompt に訂正・やり直しパターン（「いいえ」「違う」「vitest です」等）
- 同一 cwd で gitBranch 横断の繰り返し指摘

**更新対象（Copilot の copilot-instructions.md 相当）:**
- `{cwd}/CLAUDE.md`
- `{cwd}/.claude/CLAUDE.md`
- `{cwd}/.claude/rules/**/*.md`
- `~/.claude/CLAUDE.md`（グローバル指摘の場合）

**注意:** 障害対応セッションのノイズを `--exclude-since` / `--stable-days 7` で除外可能にする

### `retroscope reindex`

上記 Ingest 参照。

### `retroscope status`

インデックス状態の確認（最終 ingest 時刻、セッション数、DB サイズ、未取り込みファイル数）。

---

## LLM 連携

| モード | 説明 |
|--------|------|
| オフライン（デフォルト） | 構造化集計 + テンプレート出力。API キー不要 |
| `--llm` | レポート文面生成のみ LLM 使用。入力は**集計済みサマリ + 代表スニペット**（生 JSONL 全量は送らない） |

LLM プロバイダは Phase 1 では未実装とし、Phase 2 で Claude API / ローカルモデルを検討。
Copilot chronicle と同様、**分析実行時に外部 API へデータが送信される**旨を README と CLI ヘルプに明記。

---

## プロジェクト構成（案）

cman と同型の **フラット構成**（`scripts/` + ルートのエントリポイント）。`src/` パッケージ化は Phase 2 以降で検討。

```
retroscope/
├── retroscope.py           # CLI エントリ（PEP 723、`uv run --script`）
├── server.py               # MCP サーバー（Phase 4、FastMCP）
├── .mcp.json               # Phase 4: cman と同形式
├── README.md
├── scripts/
│   ├── paths.py            # OS 別 PathResolver（cli / desktop / legacy）
│   ├── parser.py           # JSONL → NormalizedEvent
│   ├── ingest.py           # 増分取り込み
│   ├── desktop.py          # local_*.json（Phase 1.5）
│   ├── store.py            # sqlite3 + schema.sql 読込
│   ├── queries.py          # standup / search / metrics SQL
│   ├── standup.py
│   ├── tips.py
│   ├── cost.py
│   └── friction.py         # improve 用
├── store/
│   └── schema.sql
├── tests/
│   ├── fixtures/           # 匿名化 JSONL / local_*.json サンプル
│   ├── test_parser.py
│   └── test_ingest.py
└── skills/                 # Phase 4: /retroscope-standup 等（optional）
    └── ...
```

**cman との共通パターン:**
- ロジックは `scripts/*.py`、エントリはルートの `.py` 1 本
- MCP は `server.py` が `scripts/` を import
- テストは `tests/` + fixture JSONL

**Retroscope 独自:**
- `store/schema.sql` + stdlib `sqlite3`（cman に DB 層はない）
- CLI サブコマンド（standup / search / tips / …）

---

## 実装フェーズ

### Phase 0 — 調査完了 ✅

- Copilot `/chronicle` 機能整理
- Claude Code JSONL スキーマ観測
- cman との差分分析
- Claude Desktop ストレージ調査（索引 / JSONL 関係、OS パス、VM bundle リスク）
- ランタイム選定: **Python + uv + stdlib sqlite3**（cman 同型、`BUN_BE_BUN` / Bun 不採用）

### Phase 1 — コア（MVP）

- [ ] `retroscope.py` + `scripts/`（uv `run --script`）
- [ ] JSONL パーサ（主要 type のみ）
- [ ] `scripts/store.py` — stdlib `sqlite3` ingest + 増分更新
- [ ] `standup`, `search`, `reindex`, `status`
- [ ] テスト: fixture JSONL + パーサ単体

**完了基準:** `uv run --script retroscope.py standup` で API なしの作業一覧が出る

**Desktop 注記:** Phase 1 の JSONL ingest だけで Desktop Code タブの会話本文の大半は取り込める（CLI と同一ストレージ）。

### Phase 1.5 — Claude Desktop 索引

- [ ] `PathResolver`（macOS / Windows、legacy ディレクトリ名 fallback）
- [ ] `local_*.json` ingest + `desktop_sessions` テーブル
- [ ] `cliSessionId` join、欠落時のタイムスタンプマッチ（±30s）
- [ ] 全 `accountId/orgId` スキャン（UI 非表示セッションも含む）
- [ ] `link_status` 表示（standup / status）

**完了基準:** Desktop 専用索引と CLI JSONL が重複なく統合され、本文欠落セッションが明示される

### Phase 2 — 分析

- [ ] `token_usage` 集計
- [ ] `session_metrics` 算出
- [ ] `tips`, `cost-tips`（オフライン出力）
- [ ] FTS5 検索（任意）

### Phase 3 — improve + LLM

- [ ] 摩擦シグナル検出
- [ ] CLAUDE.md diff 提案（`--apply`）
- [ ] `--llm` レポート生成
- [ ] ノイズ除外オプション

### Phase 4 — 拡張（任意）

- [ ] `server.py` + `.mcp.json`（cman 同型 MCP プラグイン）
- [ ] スキル（`/retroscope-standup` 等）— CLI 出力をラップ
- [ ] `history.jsonl` 取り込み
- [ ] **Cowork Adapter**（`Claude-3p/` + `audit.jsonl` パーサ）
- [ ] ダッシュボード（TUI or Web）

---

## 非スコープ（初期）

- Cursor / Copilot / Codex 等の横断分析
- GitHub PR API 連携（テキスト言及の best-effort のみ）
- クラウド同期・チーム共有
- cman MCP ツールとの統合（併用は可能だが依存しない）
- **Bun / `bun:sqlite`**（`BUN_BE_BUN` 非対応のため。別途 Bun 必須の claude-mem 型は採用しない）
- **VM bundle**（`sessiondata.img` 等の暗号化ディスクイメージ）
- **Cowork / Chat**（Phase 4 まで見送り）

---

## Requirements

- [uv](https://docs.astral.sh/uv/)（cman と同じ）
- Python 3.12+（uv が解決）
- 追加 DB ドライバ不要（stdlib `sqlite3`）

---

## リスクと対策

| リスク | 対策 |
|--------|------|
| Claude Code JSONL スキーマ変更 | type 未知はスキップ + パーサバージョン記録 |
| 大量セッションでの ingest 遅延 | 増分 offset、並列パース、metrics はバッチ |
| improve のノイズ（障害対応） | `--stable-days`, 摩擦シグナルの閾値調整 |
| プライバシー | デフォルトオフライン、LLM 送信範囲の明示、`--dry-run` |
| subagent ログの膨張 | デフォルト除外、`--include-subagents` |
| Desktop ストレージ形式変更 | PathResolver fallback、`link_status` で欠損を可視化 |
| VM bundle 移行 | 非対応宣言、JSONL 経路が残る間は継続 |
| Python / uv 未インストール | README + `retroscope doctor`（cman と同要件） |

---

## 参考リンク

- [GitHub Copilot CLI の `/chronicle` 解説（Zenn）](https://zenn.dev/aeonpeople/articles/morihaya-20260527-copilot-cli-chronicle)
- [cman](https://github.com/laiso/cman) — ランタイム構成の参考（Python + uv + MCP）
- [GitHub #24575](https://github.com/anthropics/claude-code/issues/24575) — `BUN_BE_BUN=1` 非対応
- [45 MB of Claude Code Sessions You Don't See (DEV)](https://dev.to/arthurpro/45-mb-of-claude-code-sessions-you-dont-see-clj) — 複数アカウントと Desktop 索引
- [GitHub #29373](https://github.com/anthropics/claude-code/issues/29373) — `local-agent-mode-sessions` → `claude-code-sessions` 移行
- [GitHub #58670](https://github.com/anthropics/claude-code/issues/58670) — `local_*.json` スキーマ逆引き
- [GitHub #55418](https://github.com/anthropics/claude-code/issues/55418) — 索引あり・本文欠落パターン
- [Cowork 3P data storage (公式)](https://claude.com/docs/cowork/3p/data-storage)
- cman データソース調査（本リポジトリ内会話・2026-06-01）
- Claude Code セッションログ: `~/.claude/projects/**/*.jsonl`
