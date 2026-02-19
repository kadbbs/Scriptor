from openai import OpenAI
import os

client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

messages = [{"role": "user", "content": "你是谁,详细的完整的参数。"}]
completion = client.chat.completions.create(
    model="qwen3.5-plus",
    messages=messages,
    extra_body={"enable_thinking": True},  # 保留此参数，只是不输出思考内容
    stream=True
)


# 只输出最终回复
for chunk in completion:
    delta = chunk.choices[0].delta
    if hasattr(delta, "content") and delta.content:
        print(delta.content, end="", flush=True)

print("\n")