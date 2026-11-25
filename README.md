# AHNU CSC Ret2Shell 赛事播报

AstrBot 插件通过 Ret2Shell WebSocket 接收赛事事件，通过 HTTP API 查询赛事信息。公开、管理和运维消息分别发送到各自配置的 UMO 会话。

## 配置

在 AstrBot 插件配置中填写 WebSocket 地址。可选地配置公开、管理和运维推送目标，以及 Ret2Shell 办赛账号和密码。

在 Ret2Shell 比赛管理页面的赛事播报设置中复制完整 WebSocket 地址。地址中的 Token 可接收该场比赛的赛事事件，应妥善保管。插件不会在状态命令中显示 Token。

开启 use_markdown 配置后，命令回复和主动播报会设置 AstrBot 消息链的 Markdown 标志。目标适配器按照自身能力处理该标志。

账号留空时，赛事、排行、队伍查询和实时事件播报仍可使用。办赛账号启用题目详情和 REST 通知补偿。通知状态保存在 AstrBot 插件数据目录中。

## 命令

- /game 查询赛事信息和比赛时间
- /rank 查询总榜前十
- /challenge 题目ID 查询题目详情
- /team 队伍ID 查询队伍积分和排名
- /ret2shell_status 查看连接、赛事 ID 和推送目标状态

## 项目结构

- main.py 定义插件入口和生命周期
- commands/ 注册查询命令并格式化命令回复
- api/ 负责 Ret2Shell HTTP 和 WebSocket 连接
- services/broadcast.py 管理事件接收、赛程定时播报和消息推送
- services/events.py 解析赛事事件并映射播报级别
- services/notifications.py 跟踪通知并补播停机期间错过的新通知
- services/settings.py 读取插件配置
