import tiktoken


def count_tokens(text: str, model: str = "gpt-3.5-turbo") -> int:
    '''估算 token 数(用 tiktoken 近似)'''
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def count_messages_tokens(messages: list[dict], model: str = "gpt-3.5-turbo") -> int:
    '''估算 messages 列表的 token 数'''
    total = 0
    for msg in messages:
        total += count_tokens(msg.get("content", ""), model)
        total += 4  # 每条消息的 overhead
    total += 2  # 对话 overhead
    return total
