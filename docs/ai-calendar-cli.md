# AI 操作日历 CLI

`calendar` 仓库的唯一数据源是 `public/` 和 `internal/` 下的单事件
ICS 文件。AI 应通过 CLI 修改这些源文件，不要直接编辑 `site/`；`site/`
是构建产物，会被重新生成。

## 命令入口

在仓库根目录运行：

```bash
./bin/calendar --help
```

命令采用 GNU 风格：支持长选项、`--help`、`--version`、`-j/--json`，
错误写入 stderr 并以非零状态退出。脚本默认操作当前仓库，也可以用
`--root PATH` 指定另一个日历仓库。

## AI 操作协议

1. 先运行 `list --json`，确认已有事件和 UID。
2. 需要修改或删除时，用 `show UID --json` 核对完整事件。
3. 执行 `add`、`update` 或 `delete --yes`。
4. 运行 `validate --json`。
5. 需要检查聚合 feed 时运行 `build --json`。
6. 查看 `git diff`，确认只修改了预期的 ICS 源文件，再提交。

除非用户明确要求删除，AI 不得自动使用 `delete --yes`。修改已有事件时
不要手工替换 UID；CLI 会保留 UID、递增 `SEQUENCE`，并更新
`DTSTAMP` 和 `LAST-MODIFIED`。

## 常用命令

列出全部事件：

```bash
./bin/calendar list --json
```

按范围和日期筛选：

```bash
./bin/calendar list -s internal --from 2026-10-01 --to 2026-10-31 --json
```

按 UID、文件名或仓库相对路径查看：

```bash
./bin/calendar show 15056B96-A353-4822-B964-44C4CBF85725 --json
```

新增定时事件。标题和地点必须使用 `中文 / English` 格式；时间使用
`Asia/Shanghai`，格式为 `YYYY-MM-DDTHH:MM`。`--end` 必须显式提供：

```bash
./bin/calendar add \
  -s internal \
  --start 2026-10-15T21:30 \
  --end 2026-10-15T22:30 \
  --title '骨干会议 / SDC Core Team Meeting' \
  --location '云谷校区 / Yungu Campus H4-103' \
  --alarm-minutes 10 \
  -j
```

新增全天事件时，开始和结束都使用日期；结束日期遵循 ICS 的排他规则：

```bash
./bin/calendar add \
  -s public \
  --start 2026-11-01 \
  --end 2026-11-02 \
  --title '开放日 / Open Day' \
  -j
```

更新事件：

```bash
./bin/calendar update UID \
  --title '正式团建 / Confirmed Team Building' \
  --location '云谷校区 / Yungu Campus H4-103' \
  -j
```

更新开始时间时，CLI 会把文件移动到新的 `YYYY/MM` 目录，并保留原文件名
的标题部分：

```bash
./bin/calendar update UID \
  --start 2026-10-16T13:00 \
  --end 2026-10-16T22:00 \
  -j
```

删除必须显式确认：

```bash
./bin/calendar delete UID --yes --json
```

## 输出约定

AI 应优先使用 `--json`。成功时输出对象或数组，常见字段包括：

```json
{
  "action": "update",
  "path": "internal/2026/10/2026-10-11-sdc-team-building.ics",
  "uid": "C8835A1E-C99B-4DE1-B5BB-67F8CCFECDA0",
  "sequence": 2
}
```

`list --json` 的每个事件至少包含 `uid`、`scope`、`title`、`start`、
`end`、`location` 和 `path`。错误以 `error:` 开头并返回非零退出状态。

## 规则

- `public` 是公开活动，`internal` 是内部事件。
- 文件必须位于 `<scope>/<YYYY>/<MM>/`，且目录年月必须匹配 `DTSTART`。
- 每个源文件必须恰好有一个 `VEVENT`。
- UID 必须在整个仓库唯一。
- 标题、地点和提醒描述使用 `中文 / English`。
- 源文件使用 CRLF，ICS 每行最多 75 个 UTF-8 字节。
- `site/` 不提交；它由 `build` 或 `scripts/build_feeds.py` 生成。
