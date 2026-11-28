# Kroger 真实账户购物车集成记录

日期：2026-11-27（America/Chicago）。

## 已实现

- `KrogerAccount`：Authorization Code + PKCE S256、单次 state、精确回调地址验证、
  过期处理、refresh token 更新。账户凭证不交给商品查询 token 或模型。
- `AccountStore`：私有本地 SQLite，文件权限 0600，Git/Vercel 排除。
- `RealCartBridge`：从完成的 v2 live 本地方案导入，刷新真实商品，检查数量、
  约束、预算、库存与 PICKUP/DELIVERY，生成 5 分钟有效预览。
- `commit`：必须确认当前 plan_id；事实变化要求重新确认；账户变化、缺货、
  标签缺失或规格变化不能绕过。结果仅报告 submitted，不声称读取了真实车。
- 持久化防重复：同一 purchase_id 的并发/重复确认最多发送一次；结果未知或进程
  中断不自动重试，重新登录也不清除原提交保护。
- 本机 CLI：`connect`、`status`、`prepare`、`commit`。没有公开单账户 HTTP 写入端点。

使用步骤和限制见 [真实账户接入说明](../docs/real-kroger-cart.md)。

## 已完成验证

**212/212 离线测试通过**：原 188 条，加 24 条账户/真实提交边界测试。
测试使用受控 transport，未对真实购物车写入。包括授权错误/拒绝/过期、PKCE、
token 刷新、授权变更、预览不写入、重复及并发提交、价格变化、缺货、标签/规格变化、
403、超时及重新登录后仍阻止未知提交的重试。

真实商品只读验证通过：从现有 GPT live 结果导入 12 个鸡蛋的目标，重新读取 Kroger，
UPC `0001111060903`，1 个 12 ct 包装，PICKUP，当前小计 149 美分。
[只读报价记录](kroger_real_cart_quote_20261127.json) 明确标记无账户购物车写入。

已在官方开发者后台找到现有应用 a grocery agent，核对 Client ID；
用户在最终保存前明确确认后，新增 Cart (Public) 和回调
`http://127.0.0.1:8765/oauth/callback`。保存后的应用详情已显示正确回调、
`cart.basic:write` 及 Authorization Code grant。
授权服务短暂仍返回旧的 redirect mismatch；随后新请求已成功进入 Kroger 消费者登录页。

## 当前尚未完成的验证

目前项目 `status` 仍为 authorized=false，尚未收到购物账户的成功 OAuth 回调。
用户需在已准备好的 Kroger 消费者登录页输入自己的购物账号，并同意 a grocery agent 的
购物车授权。聊天中的完成按钮不能代替网页实际操作。

因此目前**不能声称真实购物账户已连接，或真实加购已验证通过**。
本轮未向真实账户添加任何商品，也未下单。账户连接成功后，还应先展示具体商品、
数量与实时报价，取得该次加购确认，再进行真实接口测试并人工查看 Kroger 购物车。

## 不能省略的接口边界

官方 Public Cart API v1.2.3 为 `PUT /v1/cart/add`，参数是 UPC、quantity 和
PICKUP/DELIVERY，成功返回 204。公开接口不能读取整个真实车，也不能执行本地模拟的
删除、减量、目标购物车替换或支付。调用成功是请求被接受，不等于核验最终车内容。
用户需在 Kroger 核对当前门店、履约方式、真实车数量和最终金额。

该原型为本机单用户使用。多用户网站需要独立认证、账号绑定和服务端凭证/提交账本存储，
不能把这份本地凭证文件当作公共服务共享账号。

官方依据：[Cart API](https://developer.kroger.com/api-products/api/cart-api-public)、
[OAuth](https://developer.kroger.com/api-products/api/authorization-endpoints-public)。
