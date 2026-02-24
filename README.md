# 无锡人工智能新闻聚合（单页静态）

这是一个纯静态、纯文字、中文的单页新闻聚合站。

- 数据来源：Google News RSS 关键词 `无锡 人工智能`
- 展示内容：标题 + 来源 + 时间 + 原文链接
- 更新方式：GitHub Actions 每 2 小时自动更新 `index.html`

## 本地运行

```bash
python3 -m pip install -r requirements.txt
python3 scripts/build_index.py
```

生成文件：`index.html`

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
- 脚本会尽量解析 Google News 中转链接为原文直链。
