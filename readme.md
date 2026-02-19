# 📖 Novel Agent

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![OpenAI](https://img.shields.io/badge/OpenAI-Compatible-brightgreen.svg)
![Status](https://img.shields.io/badge/Status-Active-success.svg)

**基于阿里云百炼的长篇小说自动化写作系统**

✨ 开书初始化 · 章节生成 · 持久化存储 · 状态管理 ✨

</div>

---

## 📋 目录

- [特性](#-特性)
- [快速开始](#-快速开始)
- [使用说明](#-使用说明)
- [项目结构](#-项目结构)
- [配置说明](#-配置说明)
- [命令行工具](#-命令行工具)
- [常见问题](#-常见问题)
- [许可证](#-许可证)

---

## 🎯 特性

| 特性 | 描述 |
|:---:|---|
| 🚀 **开书初始化** | 自动生成世界设定、时间线、角色、章节大纲 |
| 📝 **章节生成** | 基于大纲和设定，自动生成连贯的章节内容 |
| 💾 **持久化存储** | 每章独立文件夹，包含正文、元数据、摘要 |
| 🔄 **状态管理** | 追踪剧情进度、角色状态、伏笔回收 |
| 📚 **多书管理** | 支持同时管理多本小说 |
| 🛠️ **命令行工具** | 简洁的 CLI 接口，易于集成和自动化 |

---

## 🚀 快速开始

### 1️⃣ 克隆项目

```bash
git clone https://github.com/your-username/novel-agent.git
cd novel-agent

```


2️⃣ 创建虚拟环境
``` shell
python -m venv myenv
source myenv/bin/activate
```

3️⃣ 安装依赖

```shell
pip install -r requirements.txt
```

4️⃣ 配置 API 密钥

```shell
# 方式一：环境变量（推荐）
export DASHSCOPE_API_KEY="sk-xxxxxxxxxxxxxxxx"
```
5️⃣ 运行程序
```shell
python main.py init
```

输入示例：

```类型 (都市重生/修仙重生/科技重生): 都市重生
主角核心设定：重生回 2010 年，掌握未来十年互联网风口
金手指：精准记忆未来重大商业事件
初始目标：3 年内资产过亿
第一阶段地图：三线城市创业起步
```
撰写章节

# 写第 1 章
```
python main.py write book_20260219_140248 1
```
# 批量写第 1-10 章
```
for i in {1..10}; do python main.py write book_20260219_140248 $i; done
```
查看进度
```
# 列出所有书籍
python main.py list

# 查看某书章节列表
python main.py chapters book_20260219_140248

# 阅读指定章节
python main.py read book_20260219_140248 1
```
📁 项目结构
```


novel-agent/
├── core/                      # 核心模块
│   ├── __init__.py           # 模块导出
│   ├── initializer.py        # 开书初始化
│   ├── state.py              # 状态管理
│   └── generator.py          # 章节生成
├── books/                     # 书籍数据（自动创建）
│   └── book_YYYYMMDD_HHMMSS/
│       ├── story_state.json  # 故事总状态
│       ├── configs/          # 配置文件
│       │   ├── world.json    # 世界设定
│       │   ├── timeline.json # 时间线
│       │   └── outlines.json # 章节大纲
│       ├── chapters/         # 章节文件
│       │   ├── chapter_index.json
│       │   ├── chapter_001/
│       │   │   ├── chapter.txt
│       │   │   └── metadata.json
│       │   └── ...
│       └── summaries/        # 章节摘要
│           └── chapter_001_summary.json
├── .gitignore                # Git 忽略规则
├── requirements.txt          # Python 依赖
├── main.py                   # 主入口
└── README.md                 # 项目说明
```
| 变量名 | 说明 | 默认值 |
|:---|:---|:---|
| DASHSCOPE_API_KEY | 阿里云百炼 API 密钥 | 必填 |
| DASHSCOPE_BASE_URL | API 基础 URL | https://dashscope.aliyuncs.com/compatible-mode/v1 |

获取 API 密钥
访问 https://bailian.console.aliyun.com/
登录/注册阿里云账号
进入 API-KEY 管理页面
创建新的 API 密钥并复制

| 命令 | 说明 | 示例 |
|:---|:---|:---|
| init | 创建新书 | python main.py init |
| write | 撰写章节 | python main.py write <book_id> <chapter> |
| list | 列出书籍 | python main.py list |
| chapters | 查看章节列表 | python main.py chapters <book_id> |
| read | 阅读章节 | python main.py read <book_id> <chapter> |



## ❓ **常见问题**

**Q: API 请求超时/卡住？**  
**A**: 检查以下几点：
确认 API 密钥正确：echo $DASHSCOPE_API_KEY   
检查网络连接  
确认账户有余额  
尝试更换模型：修改 core/initializer.py 中的 self.model  


**Q: 如何修改生成参数？**  
**A**: 编辑 core/generator.py 中的提示词模板，调整：  
temperature: 创造性 (0.5-0.9)  
max_tokens: 最大输出长度  
word_count_target: 目标字数  
**Q: 书籍数据能同步到 Git 吗？**  
**A**: 默认 books/ 目录被 .gitignore 忽略。如需备份，建议：  
手动复制 books/ 到云存储  
或注释 .gitignore 中的 books/ 行（不推荐公开仓库）  

## 📄 **许可证**  
本项目采用 MIT 许可证。  
Made with ❤️ by Novel Agent Team  
⭐ Star · 🐛 Issues · 📬 Contact


