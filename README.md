# Retroscope — Claude Code セッション分析ツール

Claude Code のセッション履歴から、スタンドアップレポート・キーワード検索・改善ヒントを生成します。セッションデータの処理はすべてローカルで完結し、外部サービスへの送信は行いません。

> GitHub Copilot CLI の `/chronicle` にインスパイアされ、Claude Code のネイティブ JSONL ログを読み込み、ローカル SQLite インデックス (`~/.retroscope/store.db`) を構築します。

## 要件

- [uv](https://docs.astral.sh/uv/)
- Python 3.12+

---

## インストール

### プラグインとして使う（推奨）

Claude Code 上で以下を実行します。

```bash
/plugin marketplace add zentooo/claude-retroscope
/plugin install retroscope@retroscope
```

インストール後は、Claude Code 上でスラッシュコマンドとして呼び出せます。

> ローカルにクローン済みのリポジトリから入れる場合は、リポジトリ内で `/plugin marketplace add ./.claude-plugin` を実行してください。

### スタンドアロン CLI として使う

プラグインなしで直接スクリプトを実行することもできます。

```bash
uv run --script retroscope.py standup
uv run --script retroscope.py search "auth"
uv run --script retroscope.py tips
uv run --script retroscope.py cost-tips
uv run --script retroscope.py improve --since 7d --stable-days 7
uv run --script retroscope.py status
uv run --script retroscope.py reindex
```

---

## スキル（スラッシュコマンド）の使い方

インストール後に使えるスラッシュコマンドの一覧です。

### `/retroscope-standup` — 作業レポート

直近のセッションを集計し、プロジェクト別の作業サマリー・未完了セッションのハイライト・セッション再開コマンド (`claude --resume <id>`) を出力します。朝会・週次レビュー前に使うと便利です。

```
/retroscope-standup              # 過去 24 時間（デフォルト）
/retroscope-standup --since 7d   # 過去 1 週間
/retroscope-standup --since 3d   # 過去 3 日間
```

---

### `/retroscope-search` — キーワード検索

過去セッションの内容を全文検索します。「あのとき auth まわりで何やったっけ？」という場面で使います。マッチしたセッション一覧（プロジェクト・日時付き）とセッション再開コマンド (`cd <dir> && claude --resume <id>`) を返します。

```
/retroscope-search auth
/retroscope-search "migration schema"
```

---

### `/retroscope-tips` — ワークフロー改善ヒント

セッション履歴を分析し、Anthropic 公式ベストプラクティスに基づいた改善提案を重要度別に出します。各ヒントには対応する公式ドキュメントへのリンクが付きます。

```
/retroscope-tips                          # 過去 24 時間（デフォルト）
/retroscope-tips --since 7d               # 過去 1 週間
/retroscope-tips --focus prompting        # プロンプトの書き方
/retroscope-tips --focus skills           # SKILL.md の活用
/retroscope-tips --focus sessions         # セッション管理
/retroscope-tips --focus planning         # プランモードの使い方
```

---

### `/retroscope-cost-tips` — トークンコスト分析

トークン使用パターンを分析し、コスト削減の具体的な提案を出します。日別使用量テーブル・消費量の多いセッションのランキング・Bash 多用や Agent 多用の検出なども含まれます。

```
/retroscope-cost-tips                     # 過去 24 時間（デフォルト）
/retroscope-cost-tips --since 7d          # 過去 1 週間
/retroscope-cost-tips --focus cache       # キャッシュ効率
/retroscope-cost-tips --focus sessions    # 長時間セッション
/retroscope-cost-tips --focus skills      # スキルの再読み込み
/retroscope-cost-tips --focus subagents   # サブエージェントのコスト
```

---

### `/retroscope-improve` — CLAUDE.md 改善提案

過去セッションの「つまずき」（繰り返し発生したエラー・繰り返されたユーザーの軌道修正）を検出し、`CLAUDE.md` に書くべきルール候補をプロジェクト（`cwd`）別に提案します。「毎回同じ修正指示をしている」知識を、常設の指示として定着させるためのコマンドです。

```
/retroscope-improve                       # 過去 7 日間（デフォルト）
/retroscope-improve --since 14d           # 過去 2 週間
/retroscope-improve --stable-days 7       # 直近 7 日を除外（障害対応ノイズを回避）
/retroscope-improve --focus errors        # 繰り返しエラーのみ
/retroscope-improve --focus corrections   # 繰り返しの軌道修正のみ
/retroscope-improve --project myrepo      # 特定プロジェクトに絞る
```

> 提案はヒューリスティックです。ファイルへの自動書き込みは行わないので、内容を確認のうえ手動で取り込んでください。

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

セッションデータの収集・分析はすべてローカルで完結します。外部サービスへの送信は行いません。なお、プラグインとして使用する場合、スラッシュコマンドの解釈には Claude Code の通常の API 通信が発生します。

---

## ライセンス

[MIT](./LICENSE)
