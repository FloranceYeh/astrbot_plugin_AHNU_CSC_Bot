# AHNU:CSC.Bot

## Ret2Shell 赛事播报

AstrBot 插件通过 Ret2Shell WebSocket 接收赛事事件，通过 HTTP API 查询赛事信息。公开、管理和运维消息分别发送到各自配置的 UMO 会话。

### 配置

在 AstrBot 插件配置中填写 WebSocket 地址。可选地配置公开、管理和运维推送目标，以及 Ret2Shell 办赛账号和密码。

在 Ret2Shell 比赛管理页面的赛事播报设置中复制完整 WebSocket 地址。地址中的 Token 可接收该场比赛的赛事事件，应妥善保管。插件不会在状态命令中显示 Token。

插件的 `use_markdown` 默认关闭，查询结果、工单表单和工单通知都使用纯文本。开启后使用 Markdown 格式，aiocqhttp 会按文本显示 Markdown 源文。

账号留空时，赛事、排行、队伍查询和实时事件播报仍可使用。办赛账号启用题目详情和 REST 通知补偿。通知状态保存在 AstrBot 插件数据目录中。

### 命令

- /game 查询赛事信息和比赛时间
- /rank 查询总榜前十
- /challenge 题目ID 查询题目详情
- /team 队伍ID 查询队伍积分和排名
- /ret2shell_status 查看连接、赛事 ID 和推送目标状态
- /support 获取工单表单并在私聊中提交

群聊中按 AstrBot 的唤醒词配置发送，或 @ 机器人后发送命令。状态命令需要 AstrBot 管理员权限。

## 赛事工单

在 OneBot 群聊发送 /support 后，机器人会将表单私发给命令发送者。QQ 官方群聊在事件提供发送者的 user_openid 且用户已添加机器人的情况下，可以携带群消息 ID 私聊回复。也可以在与机器人的私聊中直接发送 /support。

在 15 分钟内私聊发回填好的表单。两种模式都接受 Markdown 表格和纯文本回复。字段名与内容之间可以用空格或冒号。省略字段名时，发两行非空文本，第一行是标题，第二行是描述。表格内的换行可用 `<br>`，竖线可写成 `\|`。

```markdown
| 字段 | 内容 |
| --- | --- |
| 工单标题 | 题目页面无法打开 |
| 问题描述 | 点击开启环境后页面显示超时。<br>刷新后仍然超时。 |
| 队伍 ID | 42 |
| 平台 ID | 00123 |
| 学号 | |
```

队伍 ID、Ret2Shell 平台 ID 和学号均可选填。用纯文本提交时，可为每个选填项另起一行并保留字段名。填写的值会随工单保存并推送。提交成功后会收到工单编号。工单保存在 AstrBot 插件数据目录的 support_tickets 子目录，每张工单对应一个 JSON 文件。

在处理工单的会话中用 /sid 查看 UMO，然后将一个或多个 UMO 填入插件配置的 support_umo 列表。工单保存后会立即向每个会话推送编号、提交者信息、标题和描述。OneBot 会显示 QQ 号和昵称。QQ 官方会显示 OpenID，只有事件提供昵称时才显示昵称。列表为空时仅保存工单。提交者会收到工单编号。

## 项目结构

- main.py 定义插件入口和生命周期
- commands/ 注册查询命令并格式化命令回复
- api/ 负责 Ret2Shell HTTP 和 WebSocket 连接
- services/broadcast.py 管理事件接收、赛程定时播报和消息推送
- services/events.py 解析赛事事件并映射播报级别
- services/notifications.py 跟踪通知并补播停机期间错过的新通知
- services/settings.py 读取插件配置
- services/support.py 校验、保存和转发私聊工单
