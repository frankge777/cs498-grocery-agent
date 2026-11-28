# 真实 Kroger 账户购物车：本机接入

程序增加了独立的账户授权与提交层，入口是 `scripts/kroger_account.py`。
实验和智能体工具仍使用本地购物车；真实写入由明确确认的提交步骤完成。

## 两种授权

原有 `KROGER_CLIENT_ID / KROGER_CLIENT_SECRET` 用于商品和门店查询，
不能代替买菜用户的授权。真实加车需要用户在 Kroger 登录并允许
`cart.basic:write`，使用 Authorization Code + PKCE 流程。

开发者应用必须启用 **Cart API (Public)**，并登记完全一致的回调地址：

```text
http://127.0.0.1:8765/oauth/callback
```

`localhost` 与 `127.0.0.1`、端口、路径、末尾斜线不同都不能混用。
若沿用其他本机地址，修改 `KROGER_REDIRECT_URI` 或传 `connect --redirect-uri`。
当前实现只支持本机 HTTP loopback 回调，不是托管网站的多用户登录系统。

开发者应用入口：[Manage Apps](https://developer.kroger.com/manage/apps)。
选现有应用的 Update，不要重新注册或重置 Client Secret。

## 1. 连接账户

```bash
.venv/bin/python scripts/kroger_account.py connect
```

终端显示 `http://127.0.0.1:8765/` 后，在同一台电脑浏览器打开。
点击 Continue to Kroger，在官方页面登录购物账户并授权。密码、验证码只在 Kroger 填写。
回调成功后显示 Connected，页面明确说明尚未加购；终端输出授权状态。
连接窗口和 state 最长等待 10 分钟，超时请重新执行 connect。

```bash
.venv/bin/python scripts/kroger_account.py status
```

status 只显示是否保存授权、token 是否未过期和能否刷新，不返回 token。
未过期也不能证明用户未在 Kroger 撤销授权；实际接口拒绝时需要重新登录。
当前仅请求 Cart scope，不请求额外的个人资料权限，因此不获取姓名或 profile ID。

## 2. 生成本地购物方案

例如用 GPT 和实时商品生成演示结果（接受的是本地草稿）：

```bash
.venv/bin/python scripts/smoke_recommended_live.py --provider codex \
  --model gpt-6-sol --accept --output outputs/my_live_plan.json
```

也可使用已有的 `outputs/gpt_codex_live_20261127.json` 作为加购候选。
后续仍须重新刷新商品、查看真实加车预览并明确确认，旧演示不是自动加车授权。

提交层仅接受从空本地车开始、已完成并验证的 v2 live 方案。
snapshot、未解决的问题、缺少数量解释、删除/减少/替换整个购物车操作都拒绝。
本机原型限制每次 1..20 个不同 UPC，每项 1..99 个包装。

## 3. 预览真实加购

```bash
.venv/bin/python scripts/kroger_account.py prepare \
  --result outputs/my_live_plan.json --modality PICKUP
```

程序从已验证方案导入数量和有效约束，再读真实商品：检查库存、履约方式、
UPC、标签、品牌/指定商品、数量解释版本和预算；规格改变需要回原购物流程重算。
输出名称、规格、UPC、包装数、单价、本次追加小计和随机 `plan_id`，有效 5 分钟。
这一步不调用真实加车接口。

默认 purchase_id 是未修改结果文件的 SHA-256；重试/重启须使用同一文件、同一 ID。
`--purchase-id` 仅用于明确的独立购买意图，不能靠换 ID 绕过结果未知的提交。

## 4. 明确确认后追加

查看预览后，只有用户明确接受这份真实加购清单，才执行：

```bash
.venv/bin/python scripts/kroger_account.py commit \
  --plan-id='<预览返回的 ID>' --confirm='<同一个 ID>'
```

提交前再次刷新商品。价格等事实变化则返回 needs_reconfirmation 和新 ID，
不写真实购物车；必须接受新预览才能继续。标签或规格冲突也不能通过确认强行跳过。

成功状态是 **submitted**：Kroger 接受了这次请求，`verified_remote_cart=false`。
请在 Kroger 网页/APP 查看实际商品和数量；程序不能把此响应说成已读取并核验整个真实车。
本接入没有下单/支付接口。

## 重要的接口边界

Kroger Public Cart API v1.2.3 提供 `PUT /v1/cart/add`，需要用户 Authorization Code 授权，
参数为 UPC、quantity 和 PICKUP/DELIVERY，成功返回 204。
当前公开接口不提供完整真实车的读取、删除、减量或结账能力。
因此是**向现有真实车追加指定数量**，不是将真实车同步成某个目标车。

查询门店 location_id 不会自动设置用户账户的取货门店；用户需在 Kroger 核对门店和履约方式。
本次追加小计不是整个真实车总价，也不是最终含税/费用/优惠的结账价格。

本地 SQLite 在发送前先记录 submitting。重复确认已提交计划只返回已有记录，
并发确认最多发送一次。超时/500/无法判断结果记为 unknown，禁止自动重试；
进程中途退出留下 submitting 时同样阻止重试。重新登录不会清除同一 purchase_id 的保护。
必须先人工查看 Kroger 真实车，不能删除数据库、修改文件或更换 ID 来盲目重发。

## 存储与部署边界

账户 token、refresh token、PKCE verifier 及提交账本保存在本机
`.kroger-account/account.sqlite3`，文件权限 0600，已被 Git 和 Vercel 上传规则排除。
refresh token 轮换会保存；OAuth state 单次使用并校验回调地址和有效期。
不把账户 token 放入模型提示、会话 token、实验 JSON、浏览器 localStorage 或公开响应。
需要自行妥善保护这份本机凭证文件；它不是加密云端用户凭证库。

这两个 Python 类可供后续本机应用调用：`KrogerAccount` 和 `RealCartBridge`。
尚未将单账户凭证暴露成公开 HTTP 端点；部署多用户网站需要独立的用户认证、
账户绑定、服务端凭证库和持久存储，不可直接共用本机账户文件。

官方依据：[Public Cart API](https://developer.kroger.com/api-products/api/cart-api-public)、
[Public Authorization Endpoints](https://developer.kroger.com/api-products/api/authorization-endpoints-public)。
