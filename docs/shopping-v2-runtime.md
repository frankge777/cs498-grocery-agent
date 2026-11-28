# Shopping v2：实现、状态与接口

这是本轮代码实现说明，区别于同目录的设计约定。真实模型实验结果另存 outputs。
v2 意图包含原始数量表达、有来源的条件、primary/fallback 和逐项 phase。
旧 v1 意图/会话保留兼容路径；响应的 schema_version 可区分，不能把 v1 路径当作 v2 数量解释。
默认 recommend 模式请求模型输出 v2；直接构造旧意图或恢复旧会话仍可运行。

## 1. 逐步执行

1. `InteractiveShoppingSession.extract_intent` 请求结构化 v2 意图，程序核验来源、
   数量类型、标签映射与营养数值依据。独立错误汇总后交给模型一次修复，
   不逐个错误增加重试；仍失败则记录原始输出与原因。
2. `coordinator_from_intent` 为每项创建状态，保存规则、原始数量与 primary 阶段。
   `active_requirement()` 按当前阶段生成生效目标，其他模块不另行编造目标。
3. `search_unresolved` 调用工具与独立语义审查。程序检查标签、数量、价格和当前事实，
   保存具体过滤原因。原始零结果和过滤后零候选都能触发有界扩展查询。
4. `ModelBasketRecommender` 只为当前待选需求提出 UPC，已确定商品只作为预算上下文。
   ID 不在候选中、重复或遗漏需求时整批拒绝并最多修复一次。
5. `_interpret_quantities` 获取商品详情，再调用 `ModelQuantityInterpreter`。
   模型解释原始单位与推荐包装，程序核验字段引用、正整数件数和可信算术。
   提取结果未知时，模型擅自提出件数也只会转为用户数量问题；
   若模型解释与提取的数量类型不一致，则转为显式确认，不静默改写目标。
6. 缺数量则提问；包装冲突/资料不足则返回 needs_quantity_review。
   不自动猜一件，也不直接把瓶、罐、盒、内含支数当同一种单位。
7. 全部可执行后由程序计算完整清单、总价与待执行购物车差量，返回
   awaiting_basket_confirmation。没有用户接受不会执行这版差量。
8. 接受后再次读商品事实，关键内容变化则新建草稿、重新确认；一致才执行并最终核查。

用户明确确认某个 UPC 的包装件数时，保存为有来源的修订，直接核验该确认，
不再重复调用模型猜测同一个已明确答复。该包装数量不会无条件转移给另一 UPC。

## 2. 缺货与其他失败

加购失败不直接等于缺货。核心恢复接受工具明确 reason，或再读详情确认 in_stock=false。
服务失败、未知标签、无效价格或未确认原因会明确暂停，不启用缺货替代。
没有库存为零的证据时，数量不足也不会被擅自转换成缺货。

- 有用户 fallback：只切换缺货需求的 phase，使用替代目标重新搜索/审查/推荐。
- 只有品类等开放要求，UPC 是模型自选：可在原范围内重新推荐，但必须确认新版整篮。
- 用户指定商品且无替代授权：返回 needs_substitution_permission。
- 用户拒绝：返回 substitution_declined，原需求保留，不能声称原任务完成。

首次搜索已发现用户指定的首选缺货，也会重新读详情确认，再进入上述分支。
仍有可用首选候选时不因另一个搜索结果缺货而提前启用替代。
拒绝后可以通过 reconsider 重新开启询问，生成新的 question_id；旧答复不可复用。
授权前会重新读取最近确认缺货商品：恢复有货则留在 primary，API 失败则保留待答问题，
不能凭等待前的旧库存自动进入 fallback。

其他需求及已加入商品保留，整篮批准清除，目标购物车只计价一次。
新推荐失败时可能保留部分已加入的本地购物车，这不等于整单成功。

v2 用 cart_policy 区分 replace_list / preserve_unlisted，优先于兼容的旧布尔字段。
明确删除清单外商品不能被“保留匹配的已有面包”误解为保留全部旧商品。
非空购物车的替换/删除要求提供原话依据；未授权删除时默认保留未列出商品。

历史候选保存当时事实及可用 ID。显式选回历史商品时必须重新读详情、审查生效范围、
核验硬条件并生成新草稿；不能复用旧 option_id、旧库存或旧价格。
本轮未选和暂时缺货不自动写入 v2 永久排除名单。
拒绝一批不确定商品后返回 needs_search_revision，等待调整/重新考虑，不永久屏蔽它们。

## 3. 对外状态与新增回答

继续使用 `/api/agent/interactive/start` 与 `/resume`，前端尚未接入。
每次使用最新 session_token，resume 一次只提交一种回答。
响应额外提供 schema_version、逐项 phase、active_requirement、selection_revision、
quantity_interpretation、库存观察和过滤记录。

缺货授权：

```json
{
  "session_token": "<最新 token>",
  "substitution_answers": {
    "answers": [{"question_id": "<返回的问题 ID>", "action": "allow_scope", "scope": "其他明确 dairy-free、nut-free 的奶"}]
  }
}
```

拒绝时 action=decline，不提交 scope。allow_scope 必须说明范围，不能只传空的“同意”。
这不是任意硬条件修改接口；预算、数量、标签继续核验，不会因为授权换品牌而自动放宽。

数量/包装解释冲突：

```json
{
  "session_token": "<最新 token>",
  "quantity_review_answers": {
    "answers": [{"question_id": "<返回的问题 ID>", "action": "confirm_selected_package_count", "amount": 2, "acknowledge_product_change": true}]
  }
}
```

该答复明确接受展示的商品/包装并指定外包装数，会保存修订并生成新报价供整篮确认。
不能把这次确认当成删除其他硬标签的授权。拒绝该商品可使用 action=replace，重新推荐。
仅缺包装数量时仍使用原有 clarification_answers，不需要 acknowledge_product_change。

已有推荐草稿的动作使用 recommendation_answer，必须带当前 recommendation_id：

- accept：接受当前整篮。
- replace + requirement_ids：v2 默认重新推荐这些项；其他需求保留。
- choose_candidates + requirement_ids：用户主动希望看候选时使用。
- set_package_counts + updates：明确修改展示商品的包装数，例如
  `[{"requirement_id":"r1","amount":3}]`；重新报价、确认后才执行。
- set_budget + budget_cents：用户明确修订预算，重算后仍超预算则返回 budget_conflict。
- select_history + requirement_id + product_id：按商品身份重新核验历史候选，生成新版草稿。

新限制/数量/商品不通过旧草稿静默执行。任意自然语言修改整份需求的通用入口尚未实现；
目前的修改入口是以上结构化合同，以及原有阻碍搜索信息的自由文本澄清。

## 4. 持久化与限制

checkpoint 保存原请求、副本形式的意图证据、追加修订、逐项规则和阶段、
候选历史、库存观察、解释、待答问题和当前草稿/批准。
同一发现过程内可复用未变化的详情，用户确认和执行检查仍重新调用详情工具。

每项每阶段一轮发现最多 3 个不同查询，同一查询失败最多重试一次，
语义审查/推荐/数量输出格式分别最多修复一次。全部调用仍受原模型、工具及时间限制。
审查修复后若个别行仍引用虚构事实，将该行标记 withheld，不作为推荐或用户选择候选；
其他逐行独立通过校验的结果可以继续使用。未知/重复/缺失 ID、整批无有效结果仍失败。
源码兼容旧 checkpoint，不会给没有保存的用户授权自动补出 fallback。

签名 token 仍是无数据库状态；未实现跨旧 token 并发锁/强重放防护、
真实账户购物车事务、任意自然语言偏好修改和完整的永久排除管理接口。
子毫升/子克的精确总量目前会要求澄清，不会静默取整。
营养数值只支持明确数值依据及 per_serving 基准；其他基准不能自动猜测。

## 5. 验证方式

受控离线测试验证程序边界，不证明模型理解所有商品。
新增测试包括缺货授权/拒绝、开放范围重荐、双项独立缺货、网络错误、
缺标签、过滤后重搜、原始数量证据、虚构营养阈值、半加仑包装、未知数量、
数量冲突、问题版本、修改包装数/预算、历史候选刷新及 HTTP 暂停恢复。

真实模型实验必须另外记录 schema_version、阶段、解释、问题和最终评分。
不改冻结数据或评分器来消除失败；冲突时模拟用户不自动接受修改原目标。
数量模拟用户仅能确认 quantity_target_mismatch：其独立档案有明确 count/volume/weight
总量、真实包装可精确满足该总量，且模型建议件数与独立算术一致。
仅包装数档案、瓶罐等形式冲突或无法精确满足总量时仍不自动同意。
