# 微信公众号接入 · WeWe RSS 部署指引

把微信公众号转成 RSS，喂给日报管道（`fetch_news.py` 直接当普通 rss 源消费）。基于微信读书后端，无需手机抓包。

## 一、启动（在本目录 wewe-rss/ 执行）
```bash
docker compose up -d
```
- 先把 `docker-compose.yml` 里的 `AUTH_CODE` 改成你自己的口令。
- 起来后浏览器打开 http://localhost:4000 ，输入 AUTH_CODE 进入后台。

## 二、登录微信读书
后台「账号管理」→「添加账号」→ 用**微信读书 App 扫码**登录。
- ⚠️ 不要勾选"24小时后自动退出"。
- 这一步是人工的，且需要一个微信读书账号（个人号即可）。

## 三、订阅公众号
「公众号源」→「添加」→ 粘贴该公众号**任意一篇文章的分享链接**（mp.weixin.qq.com/...）即可订阅。
- ⚠️ 一次别加太多、别太频繁，容易被"小黑屋"封控（约 10 个公众号 / 账号，超了等 24h 解封）。
- 建议先加我们最需要的几个：白鲸出海、DataEye短剧观察、量子位、游戏葡萄、Founder Park 等。

## 四、拿到 RSS 地址，接进日报
WeWe RSS 提供两种 feed：
- **聚合源（推荐）**：`http://localhost:4000/feeds/all.rss` —— 一个地址收下你订阅的全部公众号，日报脚本按标题自动分流。
- 单个公众号：`http://localhost:4000/feeds/{feedId}.rss`（feedId 形如 `MP_WXS_xxx`，在后台每个源详情里看）。
- 支持标题过滤：`.../feeds/all.rss?title_include=短剧|出海&title_exclude=招聘`

接入：编辑 `../sources.yaml`，找到「微信公众号(WeWe RSS)」那条，把 `url` 改成你的 feed 地址、`enabled` 改成 `true` 即可。脚本原生支持，无需改代码。

## 五、注意
- **延迟**：微信读书索引有几小时延迟，未必赶上当天 16:00 窗口最新文；`CRON_EXPRESSION` 已设 15:35 抢刷一次。
- **稳定性**：依赖微信读书非公开接口，可能被封控/改坏；务必保留"人工贴链接"兜底。
- **限额**：公众号多就多挂几个微信读书账号；或只订阅最核心的几个。
- **取 RSS 不需要 AUTH_CODE**（`/feeds` 路径公开），所以 `fetch_news.py` 无需配置 token。
