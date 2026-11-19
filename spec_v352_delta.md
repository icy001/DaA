# v3.52 增量存档（发布方内联交付，2026-11-19）

> 状态：13.0.23 节原文与两个登记哈希已收到（正文通道，逐字）。
> v3.52 指令集完整正文（3081 行、f4352ad9…）与 v3.52 config.py 仍未真实到达本机。
> 本文仅存档，不作为权威规格正文；规格替换须以发布方全文或显式授权的增量施工为准。

## 一、13.0.23 节原文（发布方副本第 2816–2844 行摘录）

13.0.23（v3.52 新增·13.1 回补第七战：发布方自己的产物没钉死，比对方的施工问题更致命）

发现（本轮实测·发布方过错）：
① v3.51 交付的 tools/compute_config_surface_cs_v1.py 本身有两个 bug：load_config(path) 声明了
   path 形参却硬编码读 config.py；且不接受位置参数 / --dump → 用户拿老版本 config 跑必报
   KeyError: 'surface_algo_id'；
② v3.51 沙箱给出的 config_surface.v349.elements.txt（703 行）不是用参考实现算法算的（用了错误的
   AST literal_eval 递归，把 tuple/list 也展开了），导致对照表与真实结构差 50+ 键；
③ 「沙箱 v3.49→v3.51 差 12 删除 + 61 新增」是错误归因——v3.49 时期没有 whitelist_exclusions；
④ v3.47 让施工方加的 SUPPORTED_KLINE_MARKETS、v3.45~v3.49 期间施工方自建的
   DATA_SOURCE_META / QI_MONITOR_ALERTS / QI_REITS_PREMIUM_THRESHOLDS / QI_NEEQ_ZERO_VOLUME_DAYS
   五个顶层大写常量，沙箱 config 漏发，导致两机常量集差 5，哈希不可能相等——发布方漏发。

确立：
① 参考脚本必须可参数化：compute_config_surface_cs_v1.py [path] [--dump PATH] [--check]
   [--legacy-v349|--legacy-whitelist FILE]；
② 参考脚本是规范的一部分——修脚本必 bump 版本；
③ 任何「同版本对照」结果必须由参考脚本在同一文件上独立跑出，禁止口头断言「差多少」；
④ 发布方漏发的业务常量，统一在 v3.52 沙箱 config 补入；
⑤ 硬要求 22 → 23 条；must_contain_markers 增 13.0.23；draft 草稿哈希重算。

冻结值（参考脚本 --check 自证）：黄金向量元素 ["A","GOLDEN","L","Z","b","c"] →
sha256=72bc8831bd7d585a256c74b123d952715841e4a5ed117addc179db183ef756b2；
常量=167 / keys_raw=644 / keys_uniq=591 / 元素=757；surface sha256 = 91a67b3752…。

## 二、两个登记件内容（发布方逐字给出）

```
f4352ad965c1fd2cbd699dea5b7bf53695e15b055070bc7e77e50e166707c684  spec_content.sha256
91a67b3752da8f505a86ab5f20c76eaafe6eaca36e15a07a0c211a0aa9929bf7  config_surface.sha256
```

注意：f4352ad9… 对应发布方 3081 行 v3.52 正文；本机当前正文是 v3.51（3f5f2f2d…），
在 v3.52 正文到达前不得写入 spec_content.sha256（登记必须与本地文件实际哈希一致）。

## 三、发布方本轮裁定（存档备查）

- 5 个顶层常量取值可保留本机现值（surface 只看名字不看取值）；EXTRA_CONSTS 中的发布方参考值未被采用。
- 发布方主张「两机键名无需改名、196/163 是坏表×跨版本产物」——施工方已用两份真实 config 文件的
  grep 与干净目标重算否证（见当轮回执 Test A / Test B），改名清单 config_surface.v352.rename_report.txt
  仍然有效，等待发布方按该报告给出精确改名映射。
