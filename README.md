# Retroscope — Claude Code セッション分析ツール

Claude Code のセッション履歴から、スタンドアップレポート・キーワード検索・改善ヒントを生成します。APIキー不要、完全オフラインで動作します。

> GitHub Copilot CLI の `/chronicle` にインスパイアされ、Claude Code のネイティブ JSONL ログを読み込み、ローカル SQLite インデックス (`~/.retroscope/store.db`) を構築します。

## 要件

- [uv](https://docs.astral.sh/uv/)
- Python 3.12+

---

## インストール

### プラグインとして使う（推奨）

Claude Code のプロジェクト内で以下を実行します。

```bash
/plugin marketplace add ./.claude-plugin
/plugin install retroscope@retroscope
```

インストール後は、Claude Code 上でスラッシュコマンドとして呼び出せます。

### スタンドアロン CLI として使う

プラグインなしで直接スクリプトを実行することもできます。

```bash
uv run --script retroscope.py standup
uv run --script retroscope.py search "auth"
uv run --script retroscope.py tips
uv run --script retroscope.py cost-tips
uv run --script retroscope.py status
uv run --script retroscope.py reindex
```

---

## スキル（スラッシュコマンド）の使い方

インストール後に使えるスラッシュコマンドの一覧です。

### `/retroscope-standup` — 作業レポート

直近のセッションを集計し、プロジェクト別に何をやったかをまとめます。朝会・週次レビュー前に使うと便利です。

```
/retroscope-standup              # 過去 24 時間（デフォルト）
/retroscope-standup --since 7d   # 過去 1 週間
/retroscope-standup --since 3d   # 過去 3 日間
```

**出力例**

- プロジェクト別の作業サマリー
- 未完了セッションのハイライト
- セッション再開コマンド (`claude --resume <id>`)

---

### `/retroscope-search` — キーワード検索

過去セッションの内容を全文検索します。「あのとき auth まわりで何やったっけ？」という場面で使います。

```
/retroscope-search auth
/retroscope-search "migration schema"
```

**出力例**

- マッチしたセッション一覧（プロジェクト・日時付き）
- セッション再開コマンド (`cd <dir> && claude --resume <id>`)

---

### `/retroscope-tips` — ワークフロー改善ヒント

セッション履歴を分析し、Anthropic 公式ベストプラクティスに基づいた改善提案を出します。

```
/retroscope-tips                          # 過去 24 時間（デフォルト）
/retroscope-tips --since 7d               # 過去 1 週間
/retroscope-tips --focus prompting        # プロンプトの書き方
/retroscope-tips --focus skills           # SKILL.md の活用
/retroscope-tips --focus sessions         # セッション管理
/retroscope-tips --focus planning         # プランモードの使い方
```

**出力例**

- 重要度別のヒント一覧
- 各ヒントに対応する公式ドキュメントへのリンク

---

### `/retroscope-cost-tips` — トークンコスト分析

トークン使用パターンを分析し、コスト削減の具体的な提案を出します。

```
/retroscope-cost-tips                     # 過去 24 時間（デフォルト）
/retroscope-cost-tips --since 7d          # 過去 1 週間
/retroscope-cost-tips --focus cache       # キャッシュ効率
/retroscope-cost-tips --focus sessions    # 長時間セッション
/retroscope-cost-tips --focus skills      # スキルの再読み込み
/retroscope-cost-tips --focus subagents   # サブエージェントのコスト
```

**出力例**

- 日別トークン使用量テーブル
- 消費量の多いセッションのランキング
- ツール別呼び出し数・Bash 多用・Agent 多用の検出
- 具体的なコスト削減アクション

---

## はじめに：インデックスの構築

Retroscope は SQLite インデックスを読み込んで動作します。**初回利用前にインデックスを構築する必要があります。**

| 利用方法 | インデックス構築 |
|----------|----------------|
| プラグイン（スラッシュコマンド） | **自動**（各コマンド実行時に差分取り込み） |
| スタンドアロン CLI | **手動**（初回のみ `reindex` が必要） |

CLI の場合、最初に一度だけ以下を実行してください。

```bash
uv run --script retroscope.py reindex
```

以降は各コマンドをそのまま使えます。インデックスの状態確認は `status` で行えます。

```bash
uv run --script retroscope.py status
```

---

## データソース

| 種別 | パス |
|------|------|
| セッションログ | `~/.claude/projects/**/*.jsonl` |
| インデックスキャッシュ | `~/.retroscope/store.db` |

- サブエージェントのログはデフォルトで除外されます。含める場合は `--include-subagents` を指定してください。
- インデックスの保存先は環境変数 `RETROSCOPE_DATA_DIR` で変更できます。

---

## プライバシー

すべての処理はローカルで完結します。外部 API への送信は行いません。

---

## フェーズ状況

- ✅ Phase 1: JSONL 取り込み、standup、search、reindex、status、MCP プラグイン
- ⏳ Phase 1.5: Desktop `local_*.json` インデックスの結合
- ✅ Phase 2: token_usage 集計、session_metrics、tips、cost-tips、FTS5 検索
- ⏳ Phase 3+: improve、`--llm` モード
