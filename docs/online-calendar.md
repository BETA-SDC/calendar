# FullCalendar 在线日历

`calendar.html` 提供日、周、月、自然季度和年视图。月视图为默认入口，
周一起始，统一使用北京时间。日和周采用日期格，季和年采用多月网格；
当前期间的活动同时列在旁边，手机显示在下方。点击日期打开当天，
编辑者可点击空白日期新建，点击活动查看或编辑。

## 静态发布

FullCalendar Standard 6.1.19、Luxon 3.7.2 和 Lucide 0.468.0 固定在
`package-lock.json`，浏览器只加载 `web/vendor/` 中的本地文件。
依赖许可证与 SHA-256 清单随站点发布。BETA 图标复用 beta 现有账号站点素材。

```bash
npm ci --ignore-scripts
npm run vendor
npm run check
.venv-build/bin/python -m pip install -r requirements-server.txt
./bin/calendar validate -j
./bin/calendar build -j
.venv-build/bin/python -m unittest discover -s tests -v
.venv-build/bin/python -m server.preview --site "$PWD/site" --port 8765
```

访问 `http://127.0.0.1:8765/`。GitHub Pages 上同版页面只读，配置文件
`calendar-config.json` 中 `api:false`，不会请求登录服务。
已有订阅页、单事件页、ICS URL 继续工作，生成的 `site/` 不提交。

## 登录与权限

beta 集成入口是 `calendar_service.beta_entry:create_app()`。
安装时把本仓库 `server/` 作为 `calendar_service` 包提供，原有
`server.registration` 仍从 `/opt/betasdc` 导入，避免模块名冲突。
该工厂创建原有 Flask 应用，然后注册日历路由；登录、账号数据库、
会话密钥、校园网络限制和 CSRF 校验均复用原服务。

- 默认角色为查看者；编辑者可维护全部事件；管理员还可授权角色。
- 启动管理员可指定已有、已验证邮箱的账号，或安装时自动选择。
- 自动模式保留已有管理员，否则选择最早的已验证密码账号；没有时创建专用
  本地管理员。随机密码保存在服务器 `bootstrap-account.json`（权限 0600），
  不打印密码。该账号使用保留的 `.invalid` 邮箱，由运维命令直接激活，
  不提供邮箱收信或找回能力；后续可授权日常账号作为管理员。
- 管理员页面使用数字账号 ID 授权，服务端校验账号存在。
- 最后一位管理员不能被撤销。
- 队列执行前再次校验角色，排队期间撤销编辑权也生效。
- 日历页面单独允许内联样式，以兼容 FullCalendar 动态布局；账号页 CSP 保持原值。

这里延续仓库的非敏感信息边界：公开仓库和既有 feeds 中的内部／待定事项
仍然公开可读，页面访问密码只控制显示；角色控制的是写入权限。
没有新增私密存储、私密订阅或个人日历隔离。

## API

所有路径以 `/api/calendar` 开头。写操作要求登录、角色、
JSON 请求体及 `X-CSRF-Token`；单请求上限 32 KiB。
事件写请求支持 `Idempotency-Key`（32 位十六进制），相同用户和内容重试返回
同一个请求；浏览器在发送前保存编号，可在网络中断后核对是否已收到。

| 方法、路径 | 行为 |
| --- | --- |
| `GET /session` | 当前账号、角色、编辑能力、CSRF token |
| `GET /events?start=...&end=...` | 与区间相交的事件，结束边界排他；不传则全部 |
| `POST /events` | 新建，返回 `202 {id,state}` 发布请求 |
| `PATCH /events/<uid>` | 部分更新，必须携带 `version` |
| `DELETE /events/<uid>` | 请求体 `{version}`，界面二次确认 |
| `GET /jobs/<id>` | 本人或管理员查询发布结果 |
| `GET /roles` | 管理员列出已授权账号 |
| `PUT /roles` | 管理员写入 `{userId,role}` |

事件写入字段：`title,location,description,sourceUrl,scope,status,start,end,
alarmMode,alarmMinutes,version`。双语字段使用 `中文 / English`；
日期表示全天，带时间表示定时；未带时区时按北京时间。
全天结束日期排他。`alarmMode` 是 `keep/clear/set`，只有 `set`
携带 `alarmMinutes`。空地点会清除 LOCATION。未传字段保持原值。

事件返回 `uid,version,recurring,actions` 等展示字段。
`version` 是源路径与 ICS 字节的 SHA-256；过期版本在入队时返回 409，
或在执行时作为失败结果返回，提示重新加载。重复事件不提供网页规则编辑；
CLI 维护不受影响。现有附件、扩展字段和未替换的提醒会保留。

## 发布进程

登录服务仍只允许 Unix socket。独立 systemd worker 负责网络和 Git，
与 Web 进程通过 `/var/lib/betasdc-calendar/calendar.sqlite3` 交换请求。
角色、请求及操作审计保存在此 SQLite；ICS 仍是唯一事件数据源。

每次发布取得跨进程文件锁，克隆最新 main，在临时目录调用受信任的本地
CLI、校验和构建，只提交 ICS 源目录，不强推。提交消息包含账号 ID、
事件 UID 和 `Calendar-Job` 编号。推送成功后原子切换 `current` 目录链接，
浏览器轮询成功才显示保存成功。

推送后断线会拉取核对提交；不能核对时保留同一请求重试。
进程重启先检查 Git 提交编号，避免重复应用。Git 冲突或构建失败不替换
当前展示。浏览器刷新后可用“检查发布状态”恢复已接受的请求。
worker 每 60 秒检查仓库其他入口的提交，使用同一文件锁校验和发布。

`releases/` 保留完整构建供恢复，运维应按保留策略清理旧版本；
备份 SQLite 和 GitHub 仓库即可保留源数据、角色及审计。

## beta 部署

目标地址是 `https://register.betasdc.duckdns.org/calendar/`，
沿用原站点的校园网访问范围。服务必须由 root 安装，普通 `jet` 用户
无法修改现有 `/opt/betasdc` 或 systemd 配置。

使用仅授权 `BETA-SDC/calendar` 的专用可写 Deploy Key。
私钥与通过可信渠道核对的 GitHub known_hosts 存为服务器上的私有文件，
凭据不进入 Git。也支持仅授权此仓库 Contents 读写的 fine-grained token。
安装脚本只读取 staging 仓库已提交的 HEAD，所以部署前先提交。

```bash
sudo sh deploy/install.sh auto /secure/calendar-deploy-key /secure/github-known-hosts
```

也可用已有账号名替换 `auto`。token 模式使用两参数：
`ADMIN_USERNAME_OR_auto TOKEN_FILE`。

脚本会：

1. 备份应用、systemd drop-in、worker 和 Nginx 配置至
   `/var/backups/betasdc-calendar/<时间>/`。
2. 安装到 `/opt/betasdc-calendar`，建立独立虚拟环境。
3. 配置 `/var/lib/betasdc-calendar`、专用凭据、worker 和登录服务 drop-in。
4. 自动选择或创建管理员，首次同步构建站点。
5. 仅给 `/api/calendar/` 增加 Nginx 32 KiB 请求上限，测试配置后重载。
6. 启动 worker，并重启登录服务。

安装前检查：Python venv 可用，beta 可访问 GitHub，专用凭据有推送权，
自动管理员结果。安装后检查原登录／注册、查看者写入被拒绝、编辑者新增、
编辑和删除测试活动，检查 GitHub 提交和 feeds。页面保存后 GitHub Pages
仍需等待 Actions；系统日历订阅客户端按自身刷新策略更新。

回滚：

```bash
sudo sh deploy/rollback.sh /var/backups/betasdc-calendar/TIMESTAMP
```

回滚恢复旧应用与配置，不删除角色审计库，也不撤销已推送的日历事件；
事件内容回退使用正常 Git 提交。无需修改已有 Caddy 配置或放宽登录服务
的网络隔离。
