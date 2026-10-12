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

先判断输入类型：

- 只有自然语言描述：使用 `add`，让 CLI 从参数生成规范 ICS。
- 已经提供 `.ics` 文件：使用 `import`，让 CLI 保留原文件的事件内容和
  UID，只补仓库要求的范围、双语字段和元数据。

1. 用 `search '关键词' --json` 定位事件；需要全量清单时用 `list --json`。
2. 对已有事件用 `show UID --json`；对外部文件先用 `inspect FILE --json`，
   查看 UID 是否已存在、时间和需要补充的双语字段。
3. 自然语言输入执行 `add`；ICS 输入执行 `import`。
4. 需要修改或删除已有事件时，执行 `update` 或 `delete --yes`。
5. 不确定参数时，先用 `--dry-run --json` 预览；完成写入后运行 `validate --json`。
6. 需要检查聚合 feed 时运行 `build --json`。
7. 查看 `git diff`，确认只修改了预期的 ICS 源文件，再提交。

除非用户明确要求删除，AI 不得自动使用 `delete --yes`。修改已有事件时
不要手工替换 UID；CLI 会保留 UID、递增 `SEQUENCE`，并更新
`DTSTAMP` 和 `LAST-MODIFIED`。

## 高效查询与导入诊断

按标题、地点、UID 或路径搜索，忽略英文大小写。空格分隔的关键词必须
全部匹配；也可以给 `list` 添加 `--query`：

```bash
./bin/calendar search 'math help' --json
./bin/calendar search 'H4-121' -s public --status planned \
  --fields uid,title,start,path --limit 5
```

`list`、`search`、`agenda` 共享 `--scope`、`--status`、`--from`、
`--to`、`--limit`、`--fields`。结果按开始时间排序。`--limit` 必须是正整数；
`--fields` 接受逗号分隔的字段名，并始终输出 JSON。常用字段：
`uid,title,start,end,location,path,scope,status,requiresKey,url`。
完整字段与 `list --json` 一致。日期必须是 `YYYY-MM-DD`。
`list/search` 的日期过滤按活动开始日期，包含两端。

查看未来七天，或指定日程窗口：

```bash
./bin/calendar agenda --json
./bin/calendar agenda --from 2026-10-12 --days 14 --fields uid,title,start,end
./bin/calendar agenda --from 2026-10-12 --to 2026-10-31 --status tentative -j
```

`agenda` 默认从北京时间今天开始，共七天；`--to` 优先于 `--days`。
它返回与窗口有交集的活动，包括之前开始、仍未结束的跨日活动。
全天事件的结束日期不包含在活动内。查询依据源文件的 DTSTART/DTEND，
不会展开 RRULE/RDATE 的重复实例。

导入前诊断外部文件，不写入源文件：

```bash
./bin/calendar inspect '/path/to/event.ics' --json
```

返回 `eventCount`、`singleEvent` 和 `events`。每项包含 UID、标题、地点、
时间、状态、提醒数量、`existingPath` 和 `issues`。
`existingPath` 非空说明 UID 已存在；`issues` 列出缺失 UID/开始时间、
需要双语覆盖的字段及无效时间范围等问题。多事件文件可以检查，但
`import` 仍只接受恰好一个事件。检查结果包含问题时仍正常返回 JSON；
读取或解析失败时非零退出。

## 预览、改期与链接

`add`、`import`、`update`、`shift`、`delete` 支持 `--dry-run`，
执行同样的参数、UID、路径冲突及时间范围检查，但不创建、修改或删除源文件。
返回 `dryRun: true`；增改和导入还返回拟写入的 `event`。
新建预览中的随机 UID 不会保留到下一次调用；需要固定身份时给 `add`
显式传入 `--uid`。删除预览仍需 `--yes`。

```bash
./bin/calendar import '/path/to/event.ics' -s public \
  --status tentative --title '活动 / Event' --dry-run -j
./bin/calendar update UID --start 2026-10-16T19:00 --dry-run -j
```

`update --start` 省略 `--end` 时自动保留原时长。定时与全天类型之间
转换必须同时提供 `--end`。结束时间必须晚于开始时间。
带时区偏移的输入会转换为 `Asia/Shanghai`，秒数会保留。

整体前移或后移，保留 UID、时长、提醒和其他事件字段：

```bash
./bin/calendar shift UID --days 7 --dry-run -j
./bin/calendar shift UID --days -1 --minutes 30 -j
```

`--days` 和 `--minutes` 可以为负数，但总参数不能都为零。
全天活动只允许按整天移动。跨月/年会自动移动源文件，递增
`SEQUENCE` 并更新时间戳。缺少 DTEND 或含重复规则/例外的活动不支持
`shift`；重复活动需要明确编辑相关时间字段。

一次获取活动下载/订阅链接、所属范围订阅、状态订阅和月份订阅：

```bash
./bin/calendar links UID --json
```

返回 `links.event/scope/status/month`，每项包含 `https` 与 `webcal`。
这些地址按发布规则生成，不会联网检查部署状态。
`requiresKey` 只表示网页是否需要解锁，不代表 ICS URL 有权限保护。

## 常用命令

事件有“可见范围”和“事件状态”两组标签。范围由 `-s public/internal`
指定，状态由 `--status planned/tentative` 指定。`add` 默认为计划事件；
`import` 默认保留原 ICS 状态，未标注状态的旧事件视为计划事件。
`list/show --json` 返回 `status`、`statusLabel` 和 `requiresKey`。
内部事件以及所有待定事件都标记为需要密钥。

```bash
./bin/calendar list -s public --status tentative --json
./bin/calendar add -s public --status tentative \
  --start 2026-11-01T14:00 --end 2026-11-01T16:00 \
  --title '待定讲座 / Tentative Talk' --json
./bin/calendar update UID --status planned --json
./bin/calendar import /path/to/event.ics -s internal --status tentative --json
```

状态变更保留 UID，并递增 `SEQUENCE`、更新修改时间。
`build` 默认生成全部事件，网页使用密码 `betasdc` 进行轻量拦截。
如需从生成文件中排除内部和待定事件，使用 `build --public-only --json`。
CLI 是本地管理工具，不验证网页密码。密码不会保护原始 JSON、ICS 链接
或公开仓库源文件。参见[密码访问说明](key-access.md)。

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

## 直接导入 ICS

已有 ICS 时不要把整个事件重新展开成 `add` 参数。`import` 会解析输入、
保留 `VEVENT` 的 UID、提醒、附件和 Apple 扩展字段，只规范化日历名称、
提醒描述、目标路径和 CRLF/折行格式。

如果输入文件已经是双语，最短命令是：

```bash
./bin/calendar import /path/to/event.ics -s internal -j
```

如果 SUMMARY 或 LOCATION 不是双语，只通过选项覆盖这两个字段：

```bash
./bin/calendar import /path/to/骨干会议.ics \
  -s internal \
  --title '骨干会议 / SDC Core Team Meeting' \
  --location '云谷校区 / Yungu Campus H4-103' \
  -j
```

导入默认拒绝仓库中已存在的 UID。确认输入是对已有事件的新版本时，使用
`--replace`；CLI 会在原路径更新事件、递增 `SEQUENCE` 并更新时间戳：

```bash
./bin/calendar import /path/to/revised-event.ics \
  -s internal \
  --replace \
  -j
```

`import` 不会自动猜测中文或英文翻译；缺少双语字段时，AI 只需通过
`--title` 或 `--location` 提供规范值。

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
