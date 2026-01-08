# 黑猫爬虫

> 新浪黑猫投诉数据爬虫项目，使用 Playwright 技术爬取投诉数据，支持数据解析和结构化存储，包含网页可视化展示功能

## 功能特点

- 支持关键词搜索爬取和指定链接爬取两种模式
- 自动登录状态保存，避免频繁登录
- 支持无头模式（Headless）和极速模式
- 实时显示采集进度和状态
- 自动数据结构化解析，提取投诉对象、投诉要求等信息
- 支持 JSON 和 CSV 两种输出格式
- 提供友好的 Web 可视化界面
- 支持多关键词批量采集

## 环境要求

- Python 3.9+
- Playwright 浏览器驱动

## 安装步骤

### 1. 克隆项目

```bash
git clone https://github.com/Wpandios/HeimaoData.git
cd HeimaoData
```

### 2. 创建虚拟环境（推荐）

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows
```

### 3. 安装依赖

```bash
pip install playwright httpx openai tqdm
playwright install chromium
```

## 使用方法

### 方式一：Web 界面（推荐）

1. 启动服务器：

```bash
python scripts/sina_tousu_crawler.py
```

2. 浏览器会自动打开 Web 界面（或访问 http://127.0.0.1:8765）

3. 使用步骤：

   a. **登录会话管理**
   - 点击"打开登录页"按钮，在弹出的浏览器中完成登录
   - 登录完成后，点击"保存会话状态"按钮保存登录状态

   b. **配置采集参数**
   - 选择采集模式：关键词采集 或 指定链接采集
   - 关键词采集：输入关键词（支持多个，逗号分隔），设置类型参数 t（默认为 1）
   - 指定链接采集：输入目标页面 URL
   - 设置其他参数：无头模式、极速模式、滚动间隔、输出格式

   c. **开始采集**
   - 点击"开始采集"按钮
   - 实时监控采集进度
   - 采集完成后，数据文件将保存在 `data/` 目录下

### 方式二：命令行模式

#### 登录模式

```bash
python scripts/sina_tousu_crawler.py --mode login
```

#### 爬取模式

```bash
python scripts/sina_tousu_crawler.py --mode crawl --keyword "泰深优选" --t 1 --format both --headless
```

参数说明：
- `--mode`: 模式选择（login/crawl）
- `--keyword`: 搜索关键词
- `--t`: 类型参数（默认为 1）
- `--format`: 输出格式（json/csv/both，默认为 both）
- `--headless`: 无头模式（默认为 True）
- `--scroll_interval`: 滚动间隔（秒，默认为 2.5）
- `--storage_state`: 登录状态文件路径（默认为 data/sina_storage_state.json）
- `--out_dir`: 输出目录（默认为 data）

## 配置说明

配置文件位于 `config/sina_crawl.json`：

```json
{
  "keywords": ["泰深优选"],
  "headless": true
}
```

### 配置项说明

- `keywords`: 默认关键词列表
  - **作用**: 预设常用关键词，方便快速启动爬虫任务
  - **必要性**: 可选，但推荐设置以提高使用效率
  - **使用场景**: 当需要定期采集相同关键词的数据时，避免每次手动输入

- `headless`: 是否使用无头模式
  - **作用**: 控制浏览器是否显示窗口
  - **必要性**: 可选，默认为 true
  - **使用场景**: 
    - `true`: 后台运行，不显示浏览器窗口，适合服务器环境
    - `false`: 显示浏览器窗口，方便调试和观察爬取过程

### 配置文件的重要性

1. **提高效率**: 避免重复输入相同的配置参数
2. **便于管理**: 集中管理爬虫的默认行为
3. **团队协作**: 统一团队内的爬虫配置标准
4. **快速切换**: 通过修改配置文件快速切换不同的爬取策略

## 输出格式

### 原始数据格式

采集的原始数据包含以下字段：
- `title`: 投诉标题
- `content`: 投诉内容
- `time`: 投诉时间
- `href`: 投诉详情链接

### 结构化数据格式

自动解析后的结构化数据包含以下字段：
- `date`: 投诉日期
- `title`: 投诉标题
- `summary`: 投诉摘要
- `object`: 投诉对象
- `demands`: 投诉要求
- `href`: 投诉详情链接

### 文件命名规则

- 原始数据：`{关键词}_{时间戳}.json` / `{关键词}_{时间戳}.csv`
- 结构化数据：`{关键词}_structured_{时间戳}.json` / `{关键词}_structured_{时间戳}.csv`

## 示例数据

项目提供了示例数据供参考，位于 `data/` 目录：

### 原始数据示例 (example_data.json)

```json
{
  "title": "2025-11-23 于黑猫投诉平台发起\n信用飞\n\n本人在2024年12月25日通过信用飞借款8000元分12期，每月要还803.65元其中每个月担保费70.21元，2025年4月12日通过信用飞借款6400元分6期，每月要还1181.39元，2025年10月28日信用飞扣款会员费349元，本人没有享受到信用飞的会员政策，综合年化率超过国家标准，要求退还担保费，高利息费！会员费！\n\n[投诉对象]信用飞App\n[投诉要求]退息费，退会员费",
  "content": "本人在2024年12月25日通过信用飞借款8000元分12期，每月要还803.65元其中每个月担保费70.21元，2025年4月12日通过信用飞借款6400元分6期，每月要还1181.39元，2025年10月28日信用飞扣款会员费349元，本人没有享受到信用飞的会员政策，综合年化率超过国家标准，要求退还担保费，高利息费！会员费！",
  "time": "",
  "href": "https://tousu.sina.com.cn/complaint/view/17390396995/?sld=1d3d6cfaf9d2ade0cbc839a8ce3deb0c",
  "keyword": "信用飞"
}
```

### 结构化数据示例 (example_data_structured.csv)

```csv
date,title,summary,object,demands,href
2025-11-23,信用飞,本人在2024年12月25日通过信用飞借款8000元分12期，每月要还803.65元其中每个月担保费70.21元，2025年4月12日通过信用飞借款6400元分6期，每月要还1181.39元，2025年10月28日信用飞扣款会员费349元，本人没有享受到信用飞的会员政策，综合年化率超过国家标准，要求退还担保费，高利息费！会员费！,信用飞App,退息费，退会员费,https://tousu.sina.com.cn/complaint/view/17390396995/
2025-12-13,信用飞,我于2023年7月22日在信用飞平台借款4万元，于8月22日还款4010.93元，并于8月31日提前结清还款，但提前还款时，信用飞多收取4347.98元利息费用（担保费及利息），现要求信用飞平台退还多收取的4347.89元利息费用（包含担保费及利息）。,信用飞App,退还多余担保费,https://tousu.sina.com.cn/complaint/view/17391181466/
2025-11-18,信用飞,信用飞，该平台多次投诉后仍旧违规催收，因个人平台导致逾期，前期有和客服进行协商沟通，期间信用飞平台催收多次以私人号码打电话，言语辱骂，威胁恐吓，信用飞平台不理睬，仍旧包庇恶意催收。现如今信用飞依旧多次纵容催收以私人号码或虚拟号码进行骚扰，威胁等。证据确凿！且信用飞平台包含多种担保费，逾期利息高达...,信用飞App,停止骚扰,调整利率,道歉赔偿/解释,处罚,销账,撤销征信问题,https://tousu.sina.com.cn/complaint/view/17390205379/
```

完整示例数据文件：
- [example_data.json](data/example_data.json) - 原始数据示例
- [example_data_structured.csv](data/example_data_structured.csv) - 结构化数据示例

## 数据解析工具

项目提供了独立的数据解析工具 `scripts/parse_complaints.py`：

```bash
python scripts/parse_complaints.py --input data/泰深优选_20251224_135035.json --output data/泰深优选_parsed.csv
```

解析后的数据包含以下字段：
- `date`: 投诉日期
- `title`: 投诉标题
- `description`: 投诉描述
- `complaint_object`: 投诉对象
- `complaint_request`: 投诉要求（标准化）
- `status`: 投诉状态
- `amount_list`: 涉及金额列表
- `source_file`: 源文件
- `block_index`: 记录索引

## 目录结构

```
HeimaoData/
├── config/                 # 配置文件目录
│   └── sina_crawl.json    # 爬虫配置文件
├── data/                   # 数据输出目录
│   ├── *.json             # 原始 JSON 数据
│   ├── *.csv              # 原始 CSV 数据
│   └── *_structured_*.csv  # 结构化数据
├── output/                 # 日志输出目录
│   └── sina_crawl.log     # 爬虫日志
├── scripts/                # 脚本目录
│   ├── sina_tousu_crawler.py  # 主爬虫脚本
│   └── parse_complaints.py    # 数据解析脚本
├── web/                    # Web 界面目录
│   └── index.html         # Web 界面
└── README.md              # 项目说明文档
```

## 常见问题

### 1. 如何避免验证码？

- 使用登录状态保存功能，先手动登录并保存会话状态
- 调整滚动间隔，避免请求过于频繁

### 2. 如何提高采集速度？

- 开启"极速模式"，会拦截图片和字体资源
- 适当减小滚动间隔（但可能降低数据完整性）

### 3. 采集数据不完整？

- 增加滚动间隔时间
- 关闭极速模式
- 手动登录并保存会话状态

### 4. 如何批量采集多个关键词？

在 Web 界面中，使用逗号分隔多个关键词：
```
泰深优选, 马上消费金融, 众花
```

### 5. 登录状态失效怎么办？

重新点击"打开登录页"完成登录，然后点击"保存会话状态"

## 技术栈

- **Playwright**: 浏览器自动化框架
- **Python 3.9+**: 编程语言
- **Tailwind CSS**: Web 界面样式
- **Font Awesome**: 图标库

## 许可证

本项目采用 MIT 许可证。

## 贡献

欢迎提交 Issue 和 Pull Request！

## 免责声明

本项目仅供学习和研究使用，请勿用于商业用途。使用本项目爬取数据时，请遵守相关法律法规和网站的使用条款。
