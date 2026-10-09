# arxiv_classify 3.0.0

本项目从 arXiv 邮件摘要中提取论文，使用 DeepSeek、Kimi 或本地 Ollama 进行两阶段筛选与分析，并提供适配桌面和手机的 Flask WebUI。

3.0 的主要变化：

- 先用短 prompt 只做 interested/irrelevant 分类；仅对 interested 论文翻译和结构化分析，减少模型消耗。
- 保留分类版本、命中规则及失败状态，分类与详细分析分别缓存。
- 自动提取 interested 论文前五幅编号图及原始图注，不调用 AI。
- 手机卡片模式支持摘要/图片切换、独立滚动、上一篇/下一篇和快速阅读标记。
- 可选 Zotero 导入、邮件报告、微信公众号草稿、Cloudflare 临时公网隧道。
- 所有凭据从本地 `.env` 或环境变量读取；仓库不包含个人密钥、邮箱、数据库、日志或论文缓存。

## 快速开始

需要 Python 3.10 或更新版本。

```bash
git clone https://github.com/jcfeng0c0-hash/arxiv_classify.git
cd arxiv_classify

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

cp .env.example .env
```

编辑 `.env`，至少填写所选推理服务的 API Key，例如：

```dotenv
API_PROVIDER=deepseek
DEEPSEEK_API_KEY=your_api_key_here
```

然后直接启动：

```bash
./start_webui.sh
```

浏览器访问 <http://127.0.0.1:5000>。首次启动会自动创建并迁移本地 SQLite 数据库。

如果不想创建虚拟环境，也可以激活已有 Python 环境后运行；脚本依次使用 `ARXIV_PYTHON`、项目 `.venv`、`python3`、`python`。

## 配置

不要修改 `src/config.py` 填入真实凭据。复制 `.env.example` 为 `.env` 后配置；`.env` 已被 Git 忽略。

常用设置：

| 配置项 | 用途 | 必需 |
| --- | --- | --- |
| `API_PROVIDER` | `deepseek`、`kimi` 或 `local` | 是 |
| `DEEPSEEK_API_KEY` | DeepSeek 在线推理 | 使用 DeepSeek 时 |
| `KIMI_API_KEY` | Kimi 在线推理 | 使用 Kimi 时 |
| `EMAIL_USER` / `EMAIL_PASS` | QQ 邮箱及授权码，用于收取 arXiv 邮件和发送报告 | 邮件流程时 |
| `ARXIV_MAIL_FOLDER` | arXiv 邮件所在 IMAP 文件夹，默认 `INBOX` | 否 |
| `EMAIL_RECIPIENTS` | 报告及隧道链接收件人，多个地址用逗号分隔 | 发送邮件时 |
| `WECHAT_*` | 微信公众号草稿接口 | 使用公众号时 |
| `ARXIV_WEBUI_WRITE_TOKEN` | Zotero 写入操作密码 | 使用 Zotero 导入时 |

也可复制 `email_list.example.txt` 为 `email_list.txt`，每行填写一个收件地址。该文件同样不会被 Git 跟踪。

本地 Ollama 模式需要 Ollama 已在 `localhost:11434` 运行，并准备代码中指定的本地模型。

## 启动方式

本地 WebUI：

```bash
./start_webui.sh
```

Cloudflare 临时公网地址（需要预先安装 `cloudflared`）：

```bash
./start_webui_cloudflare.sh
./start_webui_cloudflare.sh status
./start_webui_cloudflare.sh stop
```

如果配置了邮箱和收件人，Cloudflare 地址生成后会自动发送邮件；未配置邮件不会影响 WebUI 和隧道运行。Zotero 未安装时也会自动跳过。

公网隧道会让任何得到链接的人访问 WebUI。不要公开转发临时地址，并建议为写操作设置 `ARXIV_WEBUI_WRITE_TOKEN`。

## 每日处理

完整的已配置流程：

```bash
./run_daily.sh
```

`--all` 只启用已配置的邮件和微信公众号输出；未填写相应凭据时自动跳过。也可以指定步骤：

```bash
python __main__.py --fetch-email --extract-data
python __main__.py --analyze-data --api-provider deepseek
python __main__.py --extract-figures
python __main__.py --generate-md
```

## 分类 Prompt

筛选标准完整保留在 [`src/classification_policy.py`](src/classification_policy.py)。当前规则覆盖：

- 星系内部气体状态、分布、形态和运动学；
- 星系内部气体输运、反馈和物质循环；
- 用分子丰度或化学模型解释气体性质；
- 气体与恒星形成率、效率和耗尽时间的关系；
- 光谱、数据立方体、谱线成图和气体结构识别的新处理工具。

以 CGM、高红移、恒星结构、纯 AGN/黑洞性质或信息不足为主的论文按规则排除。修改该文件即可定制研究兴趣；prompt 内容本身不包含凭据。

## 图片、缓存和隐私

- `arxiv.db`、`downloads/`、`md/`、`logs/`、`.env`、邮件列表和运行 PID 均在 `.gitignore` 中。
- 图片优先从 arXiv HTML 提取；没有 HTML 时使用 PDF 布局启发式裁剪。
- 模型缓存只保存在本地 `downloads/inference_cache/`，不会上传到 Git。
- 发布前可运行文末的敏感信息检查。

## 测试

```bash
python -m pytest tests -q
node tests/mobile_card_gestures.cjs
node tests/mobile_card_review.cjs
```

基础敏感信息检查：

```bash
git grep -n -I -E '/home/[^/]+|API_KEY=.+|EMAIL_PASS=.+'
```

## 项目结构

```text
src/classification_policy.py  筛选 prompt 与规则版本
src/model_inference.py        分类、翻译和结构化分析
src/paper_figures.py          前五幅论文图及图注提取
src/arxiv_zotero.py           Zotero 导入
webui.py                      Flask WebUI
templates/                    桌面及手机页面
__main__.py                   每日处理命令行入口
start_webui.sh                本地启动
start_webui_cloudflare.sh     WebUI + Cloudflare 临时隧道
```

## License

MIT License，见 [`LICENSE`](LICENSE)。
