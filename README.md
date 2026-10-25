# HumanAIBrief · 每日人智协同与脑机接口资讯

面向个人或课题组阅读的公开每日文献资讯站，仿照 [NeuroBrief](https://wang-xz-neurosci.github.io/neurobrief/) 的架构，把数据源从 Europe PMC 换成 OpenAlex，并换成四个新方向：

- 人智协同教育：人机协同、AI 辅助教学与学习中的协作、认知与教学效果研究。
- 人智协同创造力：人机协同创作、生成式 AI 辅助设计/写作/艺术中的创意过程与产出研究。
- 脑机接口·心理学视角：从心理学、认知与人的因素视角研究脑机接口的可用性、用户体验与伦理。
- 人-AI 行为：人与 AI、机器人与算法系统交互中的信任、采纳、依赖、归因与决策行为研究。

一篇文献可以属于多个方向。英文检索词表与分类规则在 `config/topics.json`，不是人工质量评审。

## 数据源与边界

- 主数据源是 [OpenAlex](https://api.openalex.org/) 免费学术图谱；仅收录心理学、认知神经科学、人机/AI·心理学交叉期刊，人智协同教育额外纳入教育技术/教育学期刊。
- 期刊白名单集中在 `config/topics.json` 的 `monitored_venues`（按 `group` 分四类），主题与期刊类别的对应关系在 `topic_allowed_groups`；预印本、会议论文与纯工程/计算机来源不收录。
- 摘要保留来源原文；中文概览由 DeepSeek 仅依据题目与摘要生成，不读付费全文、不做质量评分。
- 预印本与正式发表版若 DOI 不同，尚未自动关联，可能分别展示。
- 分类来自标题、摘要与关键词，可能有误报与漏报，请以原文为准。

## 已实现

- 通过 OpenAlex 官方接口抓取文献，标准库实现，无第三方依赖。
- 固定从 2026-10-01 首次发表开始追踪；首次运行做一次全量回溯，之后每日增量并重叠 1 天，每周一补查上一自然周。
- 四方向筛选、标题/作者/DOI/关键词搜索、日期/期刊类别筛选，以及期刊白名单过滤。
- DOI/OpenAlex 编号去重，本机收藏，RIS 导出到 Zotero。
- 网站优先读取压缩的 `data.json.gz`，原始 `data.json` 保留供核对。
- RSS 文件继续提供，每份最近 50 篇；页面未放 RSS 入口。
- GitHub Actions 每天北京时间 08:17 更新并发布到 GitHub Pages。
- 任一方向抓取失败或分页不完整时保留上一次成功数据；页面显示最近成功时间，超过两天未更新会提醒。

## 首次采集前：获取免费的 OpenAlex API Key（强烈建议）

OpenAlex 无密钥时共享一个很小的免费日配额，首次全量回溯很容易触发 429 限流。建议：

1. 打开 https://openalex.org/settings/api 注册并创建一个免费 API Key（每日约 $1 额度）。
2. 在 GitHub 仓库 Settings → Secrets and variables → Actions 新建 secret，名称 **OPENALEX_API_KEY**。
3. 本机运行时用环境变量：`$env:OPENALEX_API_KEY="你的key"`。

## 中文概览与 DeepSeek（可选）

- 自动为所有有摘要的文献生成约 150–200 字中文概览；缺少摘要时如实标记，不根据题目编造。
- 模型 `deepseek-flash`，关闭思考与工具调用；预算与并发在 `config/summaries.json`。
- Secret 名称 **DEEPSEEK_API_KEY**，只配置在 GitHub Actions，实际值不写入代码、JSON 或仓库。
- 没有该密钥也不影响站点运行，文章仍显示原始摘要。

## 本机预览与验证

需要 Python 3.10+（GitHub Actions 使用 3.12；本脚本在 3.8 上也能运行）。采集只用标准库；Node.js 仅用于检查前端 JS 语法。

```powershell
# 1) 可选：设置 OpenAlex 与 DeepSeek 密钥
$env:OPENALEX_API_KEY="..."
$env:DEEPSEEK_API_KEY="..."

# 2) 首次采集（会从 2026-10-01 回溯到当天，生成 dist/data.json）
python scripts/update_papers.py

# 3) 本地只挂载已有概览缓存（不调用 DeepSeek）
python scripts/summarize_papers.py --attach-only

# 4) 生成 RSS、压缩数据并校验
python scripts/build_feeds.py
python scripts/build_public_data.py
python scripts/check_site.py

# 5) 本地预览
python -m http.server 8765 --bind 127.0.0.1 --directory dist
```

打开 http://127.0.0.1:8765/ 。可用 `?topic=bci-psychology` 等分享链接直接定位方向。

## 发布到你的 GitHub

1. 把 `config/site.json` 里的 `url` 与 `repository` 改成你的 GitHub 用户名和仓库名（例如 `USERNAME/human-ai-brief`），并同步修改 `dist/index.html` 底部「更新记录」链接。
2. 创建公开仓库，把 `dist`、`config`、`data`、`scripts`、`tests`、`.github`、`.gitignore` 和 README 推到 `main` 分支（不要漏掉 `.github/workflows/daily-update.yml`）。
3. 在 Settings → Pages 将 Source 设为 **GitHub Actions**。
4. 首次 push 后到 Actions 手动 Run workflow「Update papers and publish」；`update` 与 `deploy` 都成功才算上线。
5. 在 https://github.com/USERNAME/human-ai-brief/actions 查看运行记录，在 Pages 设置页查看正式地址。

也可以本机用 GitHub CLI 发布：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/publish_github.ps1 -Repository USERNAME/human-ai-brief
```

## 调整方向与来源

- 改主题：编辑 `config/topics.json` 的 `topics`，每个方向有 `evidence_terms`（展示命中词）、`required_term_groups`（多组“且”、组内“或”，全部命中才归类）、`exclude_terms`、可选 `require_focus_terms`（强焦点词门槛）。
- 改期刊白名单：编辑 `monitored_venues`（每条含 `group` 分类与 `issns`），并用 `topic_allowed_groups` 指定每个主题允许的期刊类别。改完需重跑 `python scripts/update_papers.py --reclassify-only` 重新过滤存量数据。
- 改起始日期：`coverage_start`。改完需要重跑一次采集（删除 `dist/data.json` 后重新 `update_papers.py` 做全量回溯）。
- 改站名/地址：`config/site.json`。

## 数据与运行边界

- OpenAlex 收录延迟、关键词遗漏仍存在；日常增量从上次成功日期接续。
- 「来源收录」字段：OpenAlex 不提供可靠的首条收录日期，站点以空值显示；「本站收录」为首次被本程序采集的时间。
- GitHub 定时任务可能延迟；公开仓库 60 天无活动时任务可能暂停。
- 免费 Pages + 标准 Ubuntu Actions 运行器；DeepSeek 按实际 token 用量计费。

官方资料：

- https://api.openalex.org/
- https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages
- https://api-docs.deepseek.com/zh-cn/quick_start/pricing/
