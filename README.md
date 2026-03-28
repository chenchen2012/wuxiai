# 无锡人工智能新闻聚合（单页静态）

这是一个纯静态、纯文字、中文的单页新闻聚合站。

- 数据来源：多源 RSS（Google News + Bing News，多关键词并行抓取）
- 聚焦主题：无锡人工智能 / 无锡AI / 无锡机器人 / 苏州人工智能 / 苏州AI / 苏州机器人 / 长三角人工智能
- 质量控制：精确 URL、标题标准化、标题模糊相似、正文相似去重，可信媒体与原始/更丰富版本优先
- 展示内容：标题 + 来源 + 时间 + 中文摘要 + 为什么值得关注 + 标签 + 原文链接
- 更新方式：GitHub Actions 每 2 小时自动更新 `index.html` 与 `data.json`

## 本地运行

```bash
python3 -m pip install -r requirements.txt
python3 scripts/build_index.py
```

生成文件：`index.html`、`data.json`

## 可选环境变量

### LLM 摘要

```bash
export WUXIAI_ENABLE_SUMMARY=true
export WUXIAI_LLM_PROVIDER=deepseek
export DEEPSEEK_API_KEY=your_key_here
# 可选
export WUXIAI_LLM_API_KEY="$DEEPSEEK_API_KEY"
export WUXIAI_LLM_BASE_URL=https://api.deepseek.com
export WUXIAI_LLM_MODEL=deepseek-chat
```

默认行为：

- 只对新抓取且正文长度足够的文章生成摘要
- 若 LLM 失败，不阻塞入库与发布
- 若正文提取过短或质量不足，不伪造摘要，会以低置信度存储

### 阈值配置

```bash
export WUXIAI_DUPLICATE_TITLE_SIMILARITY=0.88
export WUXIAI_CONTENT_SIMILARITY_THRESHOLD=0.82
export WUXIAI_MIN_RELEVANCE_SCORE=8
export WUXIAI_MIN_EXTRACTED_CONTENT_LENGTH=180
export WUXIAI_SUMMARY_MIN_CONTENT_LENGTH=260
```

## GitHub Pages 发布

1. 将仓库推送到 GitHub。
2. 打开仓库 `Settings -> Pages`。
3. `Source` 选择 `Deploy from a branch`。
4. `Branch` 选择 `main` + `/ (root)`。

## 绑定自定义域名 wuxiai.com

1. 在 `Settings -> Pages -> Custom domain` 填入：`wuxiai.com`
2. 在域名 DNS 服务商添加记录：
   - `A` 记录：`185.199.108.153`
   - `A` 记录：`185.199.109.153`
   - `A` 记录：`185.199.110.153`
   - `A` 记录：`185.199.111.153`
   - `CNAME`：`www` -> `<你的GitHub用户名>.github.io`
3. 等证书签发后，在 Pages 页面开启 `Enforce HTTPS`。

## 说明

- 项目不会转载正文，只做聚合导航。
- 脚本会做去重、相关性排序、摘要生成与来源过滤，尽量减少重复、弱相关和广告内容。
- 新增日志会说明新闻为何被跳过、为何被判定为重复、以及为何排名较高或较低。
