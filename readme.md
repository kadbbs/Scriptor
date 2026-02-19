# 创建新书
python main.py init

# 写第 1 章
python main.py write book_20260219_130500 1

# 列出书籍
python main.py list

# 查看章节列表
python main.py chapters book_20260219_130500

# 阅读章节
python main.py read book_20260219_130500 1




## 创建环境

使用qwen api  创建环境变量
```shell
export DASHSCOPE_API_KEY ="xxxxx"
```

2、推荐虚拟环境
python -m venv myenv

source myenv/bin/activate

pip install -r requirements.txt

deactivate


