"""Redis Lua 脚本常量，用于保证原子性操作。"""

# INCR + EXPIRE 原子脚本
# 用法：redis.eval(_INCR_EXPIRE_LUA, 1, key, expire_seconds)
# 返回：递增后的计数值
_INCR_EXPIRE_LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""

# DECR + 可能删除原子脚本
# 用法：redis.eval(_DECR_CLEANUP_LUA, 1, key)
# 返回：递减后的计数值
_DECR_CLEANUP_LUA = """
local current = redis.call('DECR', KEYS[1])
if current <= 0 then
    redis.call('DEL', KEYS[1])
end
return current
"""
