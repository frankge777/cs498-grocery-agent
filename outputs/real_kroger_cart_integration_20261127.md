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

初次接入时 **212/212 离线测试通过**：原 188 条，加 24 条账户/真实提交边界测试。
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

## 真实账户 OAuth 已完成

用户完成了 Kroger 消费者登录与授权，浏览器已显示 `/connected` 的 Connected 页面。
项目本地 `status` 实测为 authorized=true、access_token_unexpired=true、can_refresh=true，
scope 为 cart.basic:write。授权码已成功交换为用户 token 并保存在私有账户库中。
[非敏感授权核验记录](kroger_account_authorization_20261127.json) 不包含 token 或账户标识。
can_refresh 表示已保存 refresh token，未在有效期内强制触发真实刷新实验。

已基于原有 live 方案重新生成真实加购预览：UPC 0001111060903、12 ct、1 盒、
PICKUP、查询小计 $1.49；这一步只读取商品和保存待确认计划，不写真实购物车。

## 真实加车接口已实测通过

用户明确要求测试此前展示的 1 盒鸡蛋后，程序重新读取商品并复核：
Kroger Grade A Large White Eggs，UPC 0001111060903，12 ct，1 盒，
PICKUP，门店 02100946 查询小计 $1.49。

程序仅在商品、数量、规格、履约方式及 $1.49 报价均匹配授权时执行提交。
Kroger 真实账户接口成功返回，receipt.status=submitted、api_request_accepted=true，
checkout_performed=false。私有提交账本已持久记录 submitted，并与保存的 receipt 一致。
本次只执行一次加购提交；后续核对没有再次发送购物车写入。

这次联调还发现随机 plan_id 可以以短横线开头，直接用空格传给 argparse 时会被当成选项。
新计划 ID 已增加 cart_ 前缀，文档使用等号传参以兼容旧 ID；新增真实 CLI 解析路径的受控回归测试。
修复后当前 **213/213 离线测试通过**。该回归只调用测试 transport，没有再次向真实账户加购。

[真实加购测试记录](kroger_real_cart_test_20261127.json) 不含账户 token、refresh token 或账户标识。
这验证了项目的真实购物车写入链路，未下单或付款。

## 网页购物车内容尚待核对

程序尝试在 Kroger 网页打开 /cart，网站通过已有登录状态进入购物账户，
但跳转到 /account/account-completion，显示第 4/6 步并要求填写 Zip Code。
尚未代用户填写额外的账号资料，因此没有看到最终购物车商品与数量。
记录中 verified_remote_cart 继续为 false，不能把接口接受请求表述成网页内容已独立核验。
用户完成 Kroger 账号资料后，应检查购物车内该商品的数量及实际价格。

## 不能省略的接口边界

官方 Public Cart API v1.2.3 为 `PUT /v1/cart/add`，参数是 UPC、quantity 和
PICKUP/DELIVERY，成功返回 204。公开接口不能读取整个真实车，也不能执行本地模拟的
删除、减量、目标购物车替换或支付。调用成功是请求被接受，不等于核验最终车内容。
用户需在 Kroger 核对当前门店、履约方式、真实车数量和最终金额。

该原型为本机单用户使用。多用户网站需要独立认证、账号绑定和服务端凭证/提交账本存储，
不能把这份本地凭证文件当作公共服务共享账号。

官方依据：[Cart API](https://developer.kroger.com/api-products/api/cart-api-public)、
[OAuth](https://developer.kroger.com/api-products/api/authorization-endpoints-public)。
